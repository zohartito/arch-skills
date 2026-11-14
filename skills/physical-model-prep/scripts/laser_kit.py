#!/usr/bin/env python3
"""Laser .3dm helpers (rhino3dm, inches, true size, colour by layer). Library + CLI.

  laser_kit.py square-holes SRC.3dm --post 2.0 --burn 0.25 --out OUT.3dm [--max-hole 6] [--angle DEG]
      replace every small closed CUT curve (round post holes) with a square sized post - 2 x burn, same centre
  laser_kit.py test-strip OUT.3dm --sizes 1.3 1.4 1.5 1.6 1.7 1.8
      strip of square test holes, n scored ticks above hole n (cut it with the SAME settings as the real part)

Burn (kerf per side) measured on a ULS PLS6.150D lab laser, 3/16" basswood ply at 100 / 5 / 500: a 3.0 mm drawn circle
came out ~3.6 mm, i.e. ~0.3 mm per side. For 2 mm square brass the user skipped the test strip and cut 1.5 mm drawn
squares (burn 0.25); record the fit result here when known.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rhino3dm

MM = 1 / 25.4
LAYERS = {"CUT (red)": (255, 0, 0), "SCORE (blue)": (0, 0, 255), "ENGRAVE (black)": (0, 0, 0),
          "REFERENCE - do not cut": (0, 170, 0)}


def new_file(layers: dict | None = None, copy_from=None):
    """Empty inch file with the four standard layers (or the layers of copy_from, same order and colours)."""
    f = rhino3dm.File3dm()
    f.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Inches
    if copy_from is not None:
        for layer in copy_from.Layers:
            new = rhino3dm.Layer()
            new.Name, new.Color = layer.Name, layer.Color
            f.Layers.Add(new)
    else:
        for name, rgb in (layers or LAYERS).items():
            new = rhino3dm.Layer()
            new.Name, new.Color = name, (*rgb, 255)
            f.Layers.Add(new)
    return f


def layer_index(f, prefix: str) -> int:
    return next(i for i, layer in enumerate(f.Layers) if layer.Name.upper().startswith(prefix.upper()))


def polyline(points_in):
    return rhino3dm.PolylineCurve(rhino3dm.Point3dList([rhino3dm.Point3d(float(x), float(y), 0) for x, y in points_in]))


def square(cx, cy, side_in, deg=0.0):
    a = np.radians(deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    h = side_in / 2
    corners = [rot @ np.array(p) + (cx, cy) for p in ((-h, -h), (h, -h), (h, h), (-h, h), (-h, -h))]
    return polyline(corners)


def add(f, geometry, layer: int, name: str = ""):
    attrs = rhino3dm.ObjectAttributes()
    attrs.LayerIndex = layer
    if name:
        attrs.Name = name
    return f.Objects.Add(geometry, attrs)


def cmd_square_holes(args):
    src = rhino3dm.File3dm.Read(args.src)
    cut = layer_index(src, "CUT")
    limit = args.max_hole * MM
    out = new_file(copy_from=src)
    centres = []
    for o in src.Objects:
        bb = o.Geometry.GetBoundingBox()
        small = (bb.Max.X - bb.Min.X) < limit and (bb.Max.Y - bb.Min.Y) < limit
        if o.Attributes.LayerIndex == cut and small:
            centres.append(((bb.Min.X + bb.Max.X) / 2, (bb.Min.Y + bb.Max.Y) / 2))
            continue
        attrs = rhino3dm.ObjectAttributes()
        attrs.LayerIndex = o.Attributes.LayerIndex
        attrs.Name = o.Attributes.Name or ""
        out.Objects.Add(o.Geometry, attrs)
    side = args.post - 2 * args.burn
    for cx, cy in centres:
        add(out, square(cx, cy, side * MM, args.angle), cut, f"post hole {side:.2f} mm square (for {args.post} mm post)")
    out.Write(args.out, 7)
    print(f"{Path(args.out).name}: {len(centres)} holes replaced by {side:.2f} mm squares at {args.angle} deg")


def cmd_test_strip(args):
    f = new_file()
    cut, score = layer_index(f, "CUT"), layer_index(f, "SCORE")
    x0, y0, pitch = 0.5, 0.5, 10 * MM
    w, h = (len(args.sizes) + 1) * pitch, 14 * MM
    add(f, polyline([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)]), cut, "strip outline")
    for n, size in enumerate(args.sizes, start=1):
        cx, cy = x0 + n * pitch, y0 + 5 * MM
        add(f, square(cx, cy, size * MM), cut, f"test hole {size} mm")
        for t in range(n):
            tx = cx - (n - 1) * 0.6 * MM + t * 1.2 * MM
            add(f, polyline([(tx, y0 + 9 * MM), (tx, y0 + 12 * MM)]), score)
    f.Write(args.out, 7)
    print(f"{Path(args.out).name}: {len(args.sizes)} holes {args.sizes} mm, strip {w / MM:.0f} x {h / MM:.0f} mm")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("square-holes")
    p.add_argument("src"); p.add_argument("--out", required=True)
    p.add_argument("--post", type=float, default=2.0, help="post side, mm")
    p.add_argument("--burn", type=float, default=0.25, help="laser burn per side, mm")
    p.add_argument("--max-hole", type=float, default=6.0, help="mm; CUT curves smaller than this are holes")
    p.add_argument("--angle", type=float, default=0.0, help="square rotation, deg (match the post's plan angle)")
    p = sub.add_parser("test-strip")
    p.add_argument("out"); p.add_argument("--sizes", type=float, nargs="+", default=[1.3, 1.4, 1.5, 1.6, 1.7, 1.8])
    args = ap.parse_args(argv)
    {"square-holes": cmd_square_holes, "test-strip": cmd_test_strip}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
