#!/usr/bin/env python3
"""Seeded-defect eval for pdf_preflight.py.

Copies a real sheet PDF, plants known defects on page 1 (the answer key), runs the
preflight with --compare against the clean original, and scores which defects were
caught. The clean original is also run alone so false positives can be compared.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import fitz

PREFLIGHT = Path(__file__).resolve().parent.parent / "scripts" / "pdf_preflight.py"
POINTS_PER_INCH = 72


def plant_defects(source: Path, seeded: Path) -> list[dict]:
    document = fitz.open(source)
    page = document[0]
    width_in = page.rect.width / POINTS_PER_INCH
    x0 = width_in * 0.45
    answer_key = []

    stray_start, stray_end = fitz.Point(x0 * 72, 6 * 72), fitz.Point((x0 + 1.5) * 72, 7.2 * 72)
    page.draw_line(stray_start, stray_end, color=(0, 0, 0), width=0.6)
    answer_key.append({"defect": "stray-line", "check": "changed-region", "bbox_in": [x0, 6.0, x0 + 1.5, 7.2]})

    for offset in (0, 0.5):
        swatch = fitz.Rect((x0 + offset) * 72, 9 * 72, (x0 + offset + 0.3) * 72, 9.3 * 72)
        page.draw_rect(swatch, color=None, fill=(0.75, 0.19, 0.48))
    answer_key.append({"defect": "legend-swatch-without-symbols", "check": "swatch-only-color", "match": "#BF307A"})

    page.draw_rect(fitz.Rect(x0 * 72, 10 * 72, (x0 + 2) * 72, 11 * 72), color=None, fill=(0.2, 0.8, 0.6))
    answer_key.append({"defect": "off-palette-fill", "check": "off-palette-fills", "match": "#33CC99"})

    page.insert_text(fitz.Point(x0 * 72, 12 * 72), "label set too small", fontsize=3)
    answer_key.append({"defect": "tiny-text", "check": "small-text", "match": "3.0 pt"})

    page.insert_text(fitz.Point(x0 * 72, 12.5 * 72), "AREA TBD", fontsize=10)
    answer_key.append({"defect": "placeholder-text", "check": "placeholder-text", "match": "TBD"})

    document.save(seeded)
    return answer_key


def run_preflight(pdf: Path, out_dir: Path, extra: list[str]) -> dict:
    command = [sys.executable, str(PREFLIGHT), str(pdf), "--out", str(out_dir), "--pages", "1", "--no-tiles", *extra]
    subprocess.run(command, check=False, capture_output=True, text=True)
    return json.loads((out_dir / "report.json").read_text())


def overlaps(box_a, box_b, margin=0.25) -> bool:
    return not (box_a[2] + margin < box_b[0] or box_b[2] + margin < box_a[0]
                or box_a[3] + margin < box_b[1] or box_b[3] + margin < box_a[1])


def caught(expected: dict, findings: list[dict]) -> bool:
    for finding in findings:
        if finding["check"] != expected["check"] or finding["page"] != 1:
            continue
        if "bbox_in" in expected and finding["bbox_in"] and overlaps(expected["bbox_in"], finding["bbox_in"]):
            return True
        if "match" in expected and expected["match"].lower() in finding["message"].lower():
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="a clean, real sheet export")
    parser.add_argument("--work", type=Path, required=True, help="scratch folder")
    parser.add_argument("--palette", help="same palette argument the preflight takes")
    args = parser.parse_args()

    work = args.work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    seeded = work / "seeded.pdf"
    answer_key = plant_defects(args.pdf, seeded)
    palette_args = ["--palette", args.palette] if args.palette else []

    baseline = run_preflight(args.pdf, work / "baseline", palette_args)
    seeded_report = run_preflight(seeded, work / "seeded", [*palette_args, "--compare", str(args.pdf)])

    results = [{**item, "caught": caught(item, seeded_report["findings"])} for item in answer_key]
    detected = sum(item["caught"] for item in results)
    baseline_warnings = {(f["check"], f["message"]) for f in baseline["findings"] if f["level"] != "INFO"}
    new_warnings = [f for f in seeded_report["findings"] if f["level"] != "INFO" and (f["check"], f["message"]) not in baseline_warnings]

    for item in results:
        print(f"{'CAUGHT' if item['caught'] else 'MISSED'}  {item['defect']}  ({item['check']})")
    print(f"detection {detected}/{len(results)} · warnings on clean page 1: {len(baseline_warnings)} · "
          f"new non-INFO findings on seeded page: {len(new_warnings)}")
    (work / "eval.json").write_text(json.dumps({"results": results, "new_findings": new_warnings}, indent=2))
    raise SystemExit(0 if detected == len(results) else 1)


if __name__ == "__main__":
    main()
