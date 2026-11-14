#!/usr/bin/env python3
"""1:1 placement sheet (PDF, print at 100 %) for gluing loose model pieces onto a base, with labelled post holes and
brass cut lengths, a 50 mm check bar, orientation arrows and notes. Also writes a PNG preview and a post cut list.

    placement_sheet.py sheet.json

sheet.json (paths relative to the JSON file):
{
  "title": "GARDEN PIECES PLACEMENT", "scale_note": "1/8\\" = 1'-0\\"",
  "page_mm": [215.9, 279.4],                 # letter; tabloid = [279.4, 431.8]
  "placements": "placements.json",           # optional {stem or key: [dx, dy, dz]} print-frame shifts
  "parts": [                                 # outlines = horizontal sections of each STL, in the model frame
    {"stl": "pair-A-walls.stl", "key": "pair-A-walls", "cuts_mm": [4.0], "color": "0.5", "lw": 0.3, "label": "PAIR A walls"},
    {"stl": "table-set_MODEL-POSITION.stl", "cuts_mm": [0.3, 4.1], "color": "saddlebrown", "lw": 0.6}
  ],                                         # "fit": false = context outline, may run off the page
                                             # (the page is centred on the other parts and the posts)
  "posts": {"csv": "posts.csv", "name": "post", "x": "x_ft", "y": "y_ft", "units": "ft", "mmft": 3.175,
            "above": "above_lot_mm", "socket_mm": 4.8, "seat_offset_mm": 1.0, "size_mm": 2.0},
  "arrows": [{"text": "STREET END", "side": "top"}, {"text": "ALLEY END", "side": "bottom"}],
  "notes": ["Cut out around the garden, match the grey corners and red holes to the model, prick outlines through."],
  "out": "placement-1to1.pdf"
}

Section heights in cuts_mm are measured up from each part's own lowest point (4 mm through walls clears plinths;
0.3 mm through furniture gives the legs). Brass cut = above + socket_mm + seat_offset_mm: the height above the base
top, plus the depth the post sits in its hole, plus any difference between how the parts were designed to seat and
how they actually sit (e.g. the walls were designed 1 mm down into a pocket but sat on a flat plywood lot, so +1.0).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

MARGIN = 8.0          # mm kept clear at the page edge (printers don't print to the edge)


def main(spec_path: str) -> int:
    spec_path = Path(spec_path).resolve()
    root = spec_path.parent
    spec = json.loads(spec_path.read_text())
    page_w, page_h = spec.get("page_mm", [215.9, 279.4])
    shifts = json.loads((root / spec["placements"]).read_text()) if spec.get("placements") else {}

    parts = []
    for p in spec.get("parts", []):
        mesh = trimesh.load(root / p["stl"], force="mesh")
        key = p.get("key", Path(p["stl"]).stem)
        mesh.apply_translation(-np.array(p.get("shift", shifts.get(key, (0, 0, 0))), float))
        parts.append((p, mesh))

    posts = []
    if spec.get("posts"):
        ps = spec["posts"]
        unit = ps.get("mmft", 1.0) if ps.get("units", "mm") == "ft" else 1.0
        for row in csv.DictReader(open(root / ps["csv"])):
            above = float(row[ps["above"]])
            cut = above + ps.get("socket_mm", 0.0) + ps.get("seat_offset_mm", 0.0)
            posts.append((row[ps["name"]], float(row[ps["x"]]) * unit, float(row[ps["y"]]) * unit, above, cut))

    pts = [m.bounds[:, :2] for p, m in parts if p.get("fit", True)]
    pts += [np.array([[x, y] for _, x, y, _, _ in posts])] if posts else []
    pts = np.vstack(pts)
    lo, hi = pts.min(0), pts.max(0)
    span = hi - lo
    fits = span[0] <= page_w - 2 * MARGIN and span[1] <= page_h - 2 * MARGIN - 45
    centre = (lo + hi) / 2

    fig = plt.figure(figsize=(page_w / 25.4, page_h / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(centre[0] - page_w / 2, centre[0] + page_w / 2)
    ax.set_ylim(centre[1] - page_h / 2 + 20, centre[1] + page_h / 2 + 20)     # room for the title block on top
    ax.set_aspect("equal")
    ax.axis("off")

    for p, mesh in parts:
        for z in p.get("cuts_mm", [1.0]):
            sec = mesh.section(plane_origin=(0, 0, mesh.bounds[0][2] + z), plane_normal=(0, 0, 1))
            if sec is not None:
                for e in sec.discrete:
                    ax.plot(e[:, 0], e[:, 1], color=p.get("color", "k"), lw=p.get("lw", 0.5))
        if p.get("label"):
            ax.text(mesh.bounds[0][0], mesh.bounds[1][1] + 2.5, p["label"], fontsize=5, color=p.get("color", "k"))

    size = spec.get("posts", {}).get("size_mm", 2.0)
    for name, x, y, _, cut in posts:
        ax.add_patch(plt.Rectangle((x - size / 2, y - size / 2), size, size, fill=False, lw=0.6, color="tab:red"))
        right = x >= centre[0]
        ax.text(x + (3 if right else -3), y + 1.6, f"{name.upper()}\n{cut:.1f} mm", fontsize=5.5, color="tab:red",
                ha="left" if right else "right", va="bottom", weight="bold")

    x0, ytop = ax.get_xlim()[0] + MARGIN + 4, ax.get_ylim()[1] - MARGIN - 4
    ax.text(x0, ytop, f"{spec.get('title', 'PLACEMENT')}  -  1:1 ({spec.get('scale_note', '')})  -  PRINT AT 100 %",
            fontsize=8, weight="bold", va="top")
    y = ytop - 6
    for note in spec.get("notes", []):
        ax.text(x0, y, note, fontsize=5.5, va="top")
        y -= 4
    ax.plot([x0, x0 + 50], [y - 3, y - 3], color="k", lw=1.2)
    ax.text(x0, y - 5, "50 mm check bar: measure it after printing; if it is not 50 mm, the print was scaled",
            fontsize=5, va="top")
    xr = ax.get_xlim()[1] - MARGIN - 18
    ylo, yhi = ax.get_ylim()
    for arrow in spec.get("arrows", []):
        up = arrow.get("side", "top") == "top"
        tip = yhi - 50 if up else ylo + MARGIN + 10
        ax.annotate(arrow["text"], xy=(xr, tip), xytext=(xr, tip - 20 if up else tip + 20), fontsize=6, ha="center",
                    arrowprops=dict(arrowstyle="->", lw=0.8))

    out = root / spec.get("out", "placement-1to1.pdf")
    with PdfPages(out) as pdf:
        pdf.savefig(fig)
    fig.savefig(out.with_suffix(".png"), dpi=110)

    if posts:
        cut_csv = out.with_name(out.stem + "_post-cut-list.csv")
        with cut_csv.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["post", "above_base_mm", "cut_mm", "x_mm", "y_mm"])
            for name, x, y, above, cut in sorted(posts):
                w.writerow([name, f"{above:.1f}", f"{cut:.1f}", f"{x:.1f}", f"{y:.1f}"])
        print("cut list:", cut_csv.name)
        for name, _, _, above, cut in sorted(posts):
            print(f"  {name:14s} {cut:6.1f} mm  (above base {above:.1f})")
    print(out.name, "and", out.with_suffix(".png").name, f"| drawing span {span.round(1).tolist()} mm on a "
          f"{page_w:.0f} x {page_h:.0f} mm page" + ("" if fits else "  ** DOES NOT FIT: use a bigger page_mm or split **"))
    return 0 if fits else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
