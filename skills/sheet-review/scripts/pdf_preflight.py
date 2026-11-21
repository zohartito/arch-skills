#!/usr/bin/env python3
"""Mechanical preflight for an exported presentation-sheet PDF.

Checks what a script can check (page size, fonts, image PPI, small text, placeholder
text, scale notations, hairlines, off-palette and swatch-only colors, changes against
a previous export) and renders an overview plus overlapping print-resolution tiles so
the visual pass covers every square inch instead of a fit-to-screen glance.
"""
import argparse
import datetime as dt
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from review_state import build_contract, load_or_create, pending_review, sha256, validate_review

POINTS_PER_INCH = 72.0
PLACEHOLDER_PATTERN = re.compile(r"\b(lorem|ipsum|placeholder|todo|tbd|xxx+|tk)\b", re.IGNORECASE)
SCALE_PATTERN = re.compile(
    r"(\d+(?:\s*/\s*\d+)?\s*(?:\"|”|″|in\b|inch\b)?\s*=\s*\d+\s*(?:['’′]\s*-?\s*0?\s*(?:\"|”|″)?|ft\b|foot\b)"
    r"|\b1\s*:\s*\d{2,5}\b|\bN\.?T\.?S\.?\b)",
    re.IGNORECASE,
)
HEX_PATTERN = re.compile(r"#([0-9A-Fa-f]{6})\b")


def inches(points: float) -> float:
    return round(points / POINTS_PER_INCH, 3)


def rect_inches(rect) -> list[float]:
    return [inches(rect[0]), inches(rect[1]), inches(rect[2]), inches(rect[3])]


def to_hex(color) -> str | None:
    if not color or len(color) != 3:
        return None
    return "#" + "".join(f"{round(channel * 255):02X}" for channel in color)


def hex_to_rgb(hex_code: str) -> np.ndarray:
    hex_code = hex_code.lstrip("#")
    return np.array([int(hex_code[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def is_neutral(hex_code: str) -> bool:
    """Grays, whites and near-black ink are never palette violations."""
    rgb = hex_to_rgb(hex_code)
    return float(rgb.max() - rgb.min()) < 0.06 or float(rgb.max()) < 0.25


def load_palette(spec: str | None) -> list[str]:
    if not spec:
        return []
    source = Path(spec).expanduser()
    text = source.read_text(errors="ignore") if source.exists() else spec
    return sorted({f"#{code.upper()}" for code in HEX_PATTERN.findall(text)})


class Report:
    def __init__(self):
        self.findings = []

    def add(self, level: str, page: int, check: str, message: str, bbox=None):
        self.findings.append({"level": level, "page": page, "check": check, "message": message, "bbox_in": bbox})

    def count(self, level: str) -> int:
        return sum(1 for finding in self.findings if finding["level"] == level)


def check_page_size(page, page_no, expect, report):
    width, height = inches(page.rect.width), inches(page.rect.height)
    if expect:
        expected = sorted(expect)
        if sorted([width, height]) != expected and any(
            abs(actual - wanted) > 0.05 for actual, wanted in zip(sorted([width, height]), expected)
        ):
            report.add("FAIL", page_no, "page-size", f"{width}×{height} in, expected {expect[0]}×{expect[1]} in")
    return [width, height]


def check_fonts(page, page_no, report):
    fonts = []
    for xref, ext, font_type, basefont, *_ in page.get_fonts(full=True):
        embedded = ext not in ("n/a", "")
        fonts.append({"name": basefont, "type": font_type, "embedded": embedded})
        if not embedded:
            report.add("FAIL", page_no, "font-not-embedded", f"{basefont} ({font_type}) is not embedded")
    return fonts


def check_images(page, page_no, min_ppi, report):
    images = []
    for info in page.get_image_info(xrefs=True):
        bbox = fitz.Rect(info["bbox"])
        if bbox.width < 0.2 * POINTS_PER_INCH or bbox.height < 0.2 * POINTS_PER_INCH:
            continue
        ppi = min(info["width"] / (bbox.width / POINTS_PER_INCH), info["height"] / (bbox.height / POINTS_PER_INCH))
        images.append({"bbox_in": rect_inches(bbox), "pixels": [info["width"], info["height"]], "effective_ppi": round(ppi)})
        if ppi < min_ppi:
            report.add("WARN", page_no, "low-ppi-image", f"image at {round(ppi)} ppi (< {min_ppi})", rect_inches(bbox))
    return images


def check_text(page, page_no, min_text_pt, report):
    small_text = defaultdict(list)
    scale_notes = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            line_text = "".join(span["text"] for span in line["spans"]).strip()
            if not line_text:
                continue
            for match in SCALE_PATTERN.finditer(line_text):
                scale_notes.append({"text": line_text[:80], "match": match.group(0).strip(), "bbox_in": rect_inches(line["bbox"])})
            if PLACEHOLDER_PATTERN.search(line_text):
                report.add("WARN", page_no, "placeholder-text", f"'{line_text[:60]}'", rect_inches(line["bbox"]))
            for span in line["spans"]:
                if span["text"].strip() and span["size"] < min_text_pt:
                    small_text[round(span["size"], 1)].append(rect_inches(span["bbox"]))
    if small_text:
        sizes = ", ".join(f"{size} pt ×{len(boxes)}" for size, boxes in sorted(small_text.items()))
        smallest = min(small_text)
        report.add("WARN", page_no, "small-text", f"text below {min_text_pt} pt: {sizes} (smallest located)", small_text[smallest][0])
    return scale_notes


def check_vectors(page, page_no, palette, min_stroke_pt, report):
    colors = defaultdict(lambda: {"fill_paths": 0, "fill_area_in2": 0.0, "max_fill_in2": 0.0, "stroke_paths": 0, "example_bbox_in": None})
    hairlines = []
    for path in page.get_drawings():
        rect = path["rect"]
        area = (rect.width / POINTS_PER_INCH) * (rect.height / POINTS_PER_INCH)
        fill_hex = to_hex(path.get("fill"))
        stroke_hex = to_hex(path.get("color"))
        if fill_hex:
            entry = colors[fill_hex]
            entry["fill_paths"] += 1
            entry["fill_area_in2"] += area
            entry["max_fill_in2"] = max(entry["max_fill_in2"], area)
            entry["example_bbox_in"] = entry["example_bbox_in"] or rect_inches(rect)
        if stroke_hex:
            colors[stroke_hex]["stroke_paths"] += 1
            colors[stroke_hex]["example_bbox_in"] = colors[stroke_hex]["example_bbox_in"] or rect_inches(rect)
            width = path.get("width")
            if width is not None and width < min_stroke_pt:
                hairlines.append(rect_inches(rect))
    if hairlines:
        report.add("WARN", page_no, "hairline-strokes", f"{len(hairlines)} strokes thinner than {min_stroke_pt} pt may drop out in print", hairlines[0])

    off_palette = []
    for hex_code, entry in colors.items():
        entry["fill_area_in2"] = round(entry["fill_area_in2"], 2)
        entry["max_fill_in2"] = round(entry["max_fill_in2"], 3)
        if is_neutral(hex_code):
            continue
        swatch_only = 0 < entry["fill_paths"] <= 6 and entry["max_fill_in2"] < 1.0 and entry["stroke_paths"] == 0
        if swatch_only:
            report.add(
                "WARN", page_no, "swatch-only-color",
                f"{hex_code} appears only in {entry['fill_paths']} small fill(s) — a legend swatch with no matching "
                "vector symbols? (raster content is not counted; confirm visually)",
                entry["example_bbox_in"],
            )
        elif palette and entry["fill_area_in2"] > 0.5:
            distance = min(float(np.abs(hex_to_rgb(hex_code) - hex_to_rgb(code)).max()) for code in palette)
            if distance > 0.03:
                off_palette.append((entry["fill_area_in2"], hex_code, entry["example_bbox_in"]))
    if off_palette:
        off_palette.sort(reverse=True)
        listing = ", ".join(f"{hex_code} ({area} in²)" for area, hex_code, _ in off_palette[:8])
        report.add("WARN", page_no, "off-palette-fills", f"{len(off_palette)} fill colors not in the palette: {listing}", off_palette[0][2])
    return dict(sorted(colors.items(), key=lambda item: -item[1]["fill_area_in2"]))


def render_page(page, dpi, clip=None, gray=False) -> Image.Image:
    pixmap = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csGRAY if gray else fitz.csRGB, alpha=False)
    mode = "L" if gray else "RGB"
    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)


def tile_rects(page, tile_in, overlap_in):
    step = (tile_in - overlap_in) * POINTS_PER_INCH
    size = tile_in * POINTS_PER_INCH
    rows, cols = [], []
    y = 0.0
    while True:
        rows.append(y)
        if y + size >= page.rect.height:
            break
        y += step
    x = 0.0
    while True:
        cols.append(x)
        if x + size >= page.rect.width:
            break
        x += step
    for row_index, top in enumerate(rows):
        for col_index, left in enumerate(cols):
            rect = fitz.Rect(left, top, min(left + size, page.rect.width), min(top + size, page.rect.height))
            yield f"r{row_index + 1}c{col_index + 1}", rect


def render_views(page, page_no, out_dir, overview_dpi, tile_dpi, tile_in, overlap_in, make_tiles):
    overview = render_page(page, overview_dpi)
    tiles = []
    if make_tiles:
        tile_dir = out_dir / "tiles"
        tile_dir.mkdir(parents=True, exist_ok=True)
        draw = ImageDraw.Draw(overview)
        scale = overview_dpi / POINTS_PER_INCH
        for label, rect in tile_rects(page, tile_in, overlap_in):
            path = tile_dir / f"p{page_no}-{label}.png"
            render_page(page, tile_dpi, clip=rect).save(path)
            tiles.append({"tile": path.name, "bbox_in": rect_inches(rect)})
            draw.rectangle([rect.x0 * scale, rect.y0 * scale, rect.x1 * scale, rect.y1 * scale], outline=(230, 0, 0), width=1)
            draw.text((rect.x0 * scale + 3, rect.y0 * scale + 3), label, fill=(230, 0, 0))
    overview_path = out_dir / f"p{page_no}-overview.png"
    overview.save(overview_path)
    return overview_path.name, tiles


def compare_page(page, previous_page, page_no, out_dir, dpi, report):
    if previous_page is None:
        report.add("WARN", page_no, "compare", "page missing from the previous export")
        return None
    if abs(page.rect.width - previous_page.rect.width) > 1 or abs(page.rect.height - previous_page.rect.height) > 1:
        report.add("WARN", page_no, "compare", "page size differs from the previous export; pixel diff skipped")
        return None
    current = np.asarray(render_page(page, dpi, gray=True), dtype=np.int16)
    previous = np.asarray(render_page(previous_page, dpi, gray=True), dtype=np.int16)
    changed = np.abs(current - previous) > 40
    labels, region_count = ndimage.label(ndimage.binary_dilation(changed, iterations=max(1, dpi // 10)))
    regions = []
    for region_slice in ndimage.find_objects(labels):
        rows, cols = region_slice
        pixel_count = int(changed[region_slice].sum())
        if pixel_count < 4:
            continue
        bbox = [round(cols.start / dpi, 2), round(rows.start / dpi, 2), round(cols.stop / dpi, 2), round(rows.stop / dpi, 2)]
        regions.append({"bbox_in": bbox, "changed_pixels": pixel_count})
    regions.sort(key=lambda region: -region["changed_pixels"])
    overlay = Image.fromarray(np.uint8(np.clip(current * 0.35 + 165, 0, 255))).convert("RGB")
    overlay_pixels = np.asarray(overlay).copy()
    overlay_pixels[changed] = [230, 0, 0]
    diff_path = out_dir / f"p{page_no}-diff.png"
    Image.fromarray(overlay_pixels).save(diff_path)
    for region in regions[:25]:
        report.add("INFO", page_no, "changed-region", f"{region['changed_pixels']} px changed vs previous export", region["bbox_in"])
    if not regions:
        report.add("INFO", page_no, "changed-region", "no visible change vs previous export")
    return {"diff_png": diff_path.name, "regions": regions}


def parse_size(text: str | None):
    if not text:
        return None
    width, height = (float(part) for part in text.lower().split("x"))
    return [width, height]


def write_markdown(summary, out_dir):
    lines = [
        f"# Sheet preflight — {Path(summary['pdf']).name}",
        "",
        f"Run {summary['run_at']} · {summary['page_count']} page(s) · "
        f"FAIL {summary['counts']['FAIL']} · WARN {summary['counts']['WARN']} · INFO {summary['counts']['INFO']}",
        "",
        "Automated checks cannot see stray linework, legend-to-symbol meaning, or drawing logic.",
        "Finish with the visual pass on every tile (see SKILL.md checklist).",
        f"PDF SHA-256: `{summary['pdf_sha256']}`",
        f"Review contract SHA-256: `{summary['review_contract_sha256']}`",
        f"Full-document page scope: {summary['review_contract']['page_scope']}",
        f"Review: **{summary['review']['status']}** · `{summary['review']['path']}` · "
        f"{'strict gate' if summary['review']['required'] else 'automated-only exit status (not review acceptance)'}",
        *[f"- {error}" for error in summary['review']['errors']],
        *[f"- Open visual issue: {issue}" for issue in summary['review']['open_issues']],
        "",
        "| Level | Page | Check | Message | Where (in, from top-left) |",
        "|---|---|---|---|---|",
    ]
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    for finding in sorted(summary["findings"], key=lambda item: (order[item["level"]], item["page"])):
        lines.append(f"| {finding['level']} | {finding['page']} | {finding['check']} | {finding['message']} | {finding['bbox_in'] or ''} |")
    for page in summary["pages"]:
        lines += ["", f"## Page {page['page']} — {page['size_in'][0]} × {page['size_in'][1]} in", ""]
        lines.append(f"Overview: `{page['overview']}` · tiles: {len(page['tiles'])}")
        if page["scale_notes"]:
            lines.append("")
            lines.append("Scale notations found (check each against the drawing it labels):")
            lines += [f"- `{note['match']}` in “{note['text']}” at {note['bbox_in']}" for note in page["scale_notes"]]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="output folder for report, overview and tiles")
    parser.add_argument("--expect-size", help="expected sheet size in inches, e.g. 36x24 (either orientation)")
    parser.add_argument("--palette", help="hex codes (comma separated) or a file to read #RRGGBB codes from")
    parser.add_argument("--compare", type=Path, help="previous export of the same sheet set")
    parser.add_argument("--pages", help="comma-separated 1-based page numbers (default: all)")
    parser.add_argument("--min-ppi", type=float, default=150)
    parser.add_argument("--min-text-pt", type=float, default=6)
    parser.add_argument("--min-stroke-pt", type=float, default=0.1)
    parser.add_argument("--overview-dpi", type=int, default=30)
    parser.add_argument("--tile-dpi", type=int, default=150)
    parser.add_argument("--tile-in", type=float, default=6)
    parser.add_argument("--overlap-in", type=float, default=0.5)
    parser.add_argument("--compare-dpi", type=int, default=50)
    parser.add_argument("--no-tiles", action="store_true")
    parser.add_argument("--require-review", action="store_true",
                        help="require complete tile review: exit 0 complete, 1 fail, 2 incomplete")
    parser.add_argument("--review", type=Path, help="review JSON (default: OUT/review.json); never overwritten")
    args = parser.parse_args()
    for name in ("min_ppi", "min_text_pt", "min_stroke_pt", "overview_dpi", "tile_dpi", "tile_in", "compare_dpi"):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0 or (not name.startswith("min_") and value == 0):
            parser.error(f"--{name.replace('_', '-')} must be finite and nonnegative (positive for render sizes)")
    if not math.isfinite(args.overlap_in) or not 0 <= args.overlap_in < args.tile_in:
        parser.error("--overlap-in must be nonnegative and less than --tile-in")

    out_dir = args.out.expanduser().resolve()
    review_path = (args.review or out_dir / "review.json").expanduser().resolve()
    # Hash the exact bytes opened by MuPDF, not a later read of a possibly changed export.
    pdf_bytes = args.pdf.read_bytes()
    previous_bytes = args.compare.read_bytes() if args.compare else None
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    previous = fitz.open(stream=previous_bytes, filetype="pdf") if previous_bytes is not None else None
    palette = load_palette(args.palette)
    try:
        expect = parse_size(args.expect_size)
        page_numbers = sorted(int(part) for part in args.pages.split(",")) if args.pages else list(range(1, document.page_count + 1))
    except ValueError:
        parser.error("invalid --expect-size or --pages")
    if expect and any(not math.isfinite(value) or value <= 0 for value in expect):
        parser.error("--expect-size dimensions must be finite and positive")
    if (len(set(page_numbers)) != len(page_numbers)
            or any(p < 1 or p > document.page_count for p in page_numbers)):
        parser.error("--pages must contain unique page numbers within the document")
    # Do not let a mistaken --review alias an output that this run will overwrite.
    outputs = [out_dir / name for name in ("report.json", "report.md")]
    for page_no in page_numbers:
        outputs.extend(out_dir / f"p{page_no}-{view}.png" for view in ("overview", "diff"))
        if not args.no_tiles:
            outputs.extend(out_dir / "tiles" / f"p{page_no}-{label}.png"
                           for label, _ in tile_rects(document[page_no - 1], args.tile_in, args.overlap_in))
    if review_path in {path.resolve() for path in outputs}:
        parser.error("--review must not name a generated report or image")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = Report()
    pages = []
    for page_no in page_numbers:
        page = document[page_no - 1]
        overview, tiles = render_views(page, page_no, out_dir, args.overview_dpi, args.tile_dpi, args.tile_in, args.overlap_in, not args.no_tiles)
        page_summary = {
            "page": page_no,
            "size_in": check_page_size(page, page_no, expect, report),
            "fonts": check_fonts(page, page_no, report),
            "images": check_images(page, page_no, args.min_ppi, report),
            "scale_notes": check_text(page, page_no, args.min_text_pt, report),
            "colors": check_vectors(page, page_no, palette, args.min_stroke_pt, report),
            "overview": overview,
            "tiles": tiles,
        }
        if previous is not None:
            previous_page = previous[page_no - 1] if page_no <= previous.page_count else None
            page_summary["compare"] = compare_page(page, previous_page, page_no, out_dir, args.compare_dpi, report)
        pages.append(page_summary)

    options = {name: getattr(args, name) for name in (
        "min_ppi", "min_text_pt", "min_stroke_pt", "overview_dpi", "tile_dpi", "tile_in",
        "overlap_in", "compare_dpi", "no_tiles",
    )}
    # argparse leaves numeric defaults as ints; explicit equivalent values are floats.
    for name in ("min_ppi", "min_text_pt", "min_stroke_pt", "tile_in", "overlap_in"):
        options[name] = float(options[name])
    options.update(expect_size=sorted(expect) if expect else None, palette=palette,
                   pages=page_numbers, compare_sha256=sha256(previous_bytes) if previous_bytes is not None else None)
    contract, digest = build_contract(sha256(pdf_bytes), document.page_count, pages, options)
    template = pending_review(contract, digest)
    review, load_error = load_or_create(review_path, template)
    review_result = validate_review(contract, digest, review, report.count("FAIL"), load_error)
    summary = {
        "pdf": str(args.pdf.resolve()),
        "pdf_sha256": contract["pdf_sha256"],
        "review_contract": contract,
        "review_contract_sha256": digest,
        "pending_review": template,
        "review": {**review_result, "path": str(review_path), "required": args.require_review},
        "compare": str(args.compare.resolve()) if args.compare else None,
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "page_count": document.page_count,
        "palette": palette,
        "counts": {level: report.count(level) for level in ("FAIL", "WARN", "INFO")},
        "findings": report.findings,
        "pages": pages,
    }
    (out_dir / "report.json").write_text(json.dumps(summary, indent=2))
    write_markdown(summary, out_dir)
    print(f"{out_dir / 'report.md'} — FAIL {summary['counts']['FAIL']} · WARN {summary['counts']['WARN']} · INFO {summary['counts']['INFO']} · review {review_result['status']}")
    document.close()
    if previous is not None:
        previous.close()
    raise SystemExit(review_result["exit_code"] if args.require_review else (1 if summary["counts"]["FAIL"] else 0))


if __name__ == "__main__":
    main()
