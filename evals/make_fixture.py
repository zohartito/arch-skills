#!/usr/bin/env python3
"""Create a synthetic two-page PDF with one hairline and one 5 pt text box."""

import argparse
from pathlib import Path

import fitz

DEFAULT = Path(__file__).resolve().parent / "fixtures/sheet-review.pdf"


def build(path):
    doc = fitz.open()
    # Built-in Courier is embedded from PyMuPDF's bundled font buffer.
    font = fitz.Font("cour")
    for number in (1, 2):
        page = doc.new_page(width=792, height=612)
        page.insert_font(fontname="EvalFont", fontbuffer=font.buffer)
        page.insert_text((48, 55), "SYNTHETIC PRESENTATION SHEET", fontsize=20, fontname="EvalFont")
        page.insert_text((48, 80), "Trigger evaluation fixture | 11 x 8.5 in", fontsize=10, fontname="EvalFont")
        page.draw_rect(fitz.Rect(48, 112, 744, 528), width=0.75, color=(0.2, 0.2, 0.2))
        page.insert_text((48, 570), f"Architecture skills evaluation  /  {number} of 2", fontsize=10, fontname="EvalFont")
        if number == 1:
            page.insert_text((78, 160), "Courtyard plan diagram", fontsize=14, fontname="EvalFont")
            for rect in (fitz.Rect(100, 220, 260, 420), fitz.Rect(490, 220, 650, 420)):
                page.draw_rect(rect, color=(0, 0, 0), width=1.5, fill=(0.9, 0.9, 0.9))
            page.draw_line((280, 320), (470, 320), color=(0, 0, 0), width=0.05)
        else:
            page.insert_text((78, 160), "Section diagram", fontsize=14, fontname="EvalFont")
            page.draw_rect(fitz.Rect(100, 260, 650, 410), color=(0, 0, 0), width=1.5)
            page.draw_line((78, 410), (700, 410), color=(0, 0, 0), width=2)
            page.insert_textbox(fitz.Rect(100, 440, 500, 460), "Courtyard edge annotation", fontsize=5, fontname="EvalFont")
    doc.set_metadata({"title": "Synthetic sheet review fixture", "author": "", "creator": "arch-skills eval fixture"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return inspect(path)


def inspect(path):
    with fitz.open(path) as doc:
        hairlines = sum(d.get("type") in {"s", "fs"} and 0 <= d.get("width", 1) < .1
                        for p in doc for d in p.get_drawings())
        tiny = [s for p in doc for b in p.get_text("dict")["blocks"] if "lines" in b
                for line in b["lines"] for s in line["spans"] if s["size"] < 6]
        assert len(doc) == 2 and hairlines == 1 and len(tiny) == 1 and tiny[0]["size"] == 5
        assert all(tuple(p.rect)[2:] == (792, 612) for p in doc)
        return "PASS: 2 pages; 11 x 8.5 in; 1 hairline (0.05 pt); 1 small-text span (5 pt)"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(inspect(args.output) if args.check else build(args.output))
