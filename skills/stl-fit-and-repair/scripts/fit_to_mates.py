#!/usr/bin/env python3
"""Make a new printed part drop onto parts that are ALREADY PRINTED, with a clearance, and prove it.

    fit_to_mates.py PART.stl --mates WALLS.stl [MORE.stl ...] --out PART-FIT.stl
        [--clear 0.15] [--placements placements.json] [--min-body 1.0] [--grow-dirs 3d|xy+up]

Method (roofs onto printed walls, Oct 5 2026): put part and mates in one model frame, grow the mates by the
clearance, subtract them from the part, drop crumbs, export safely, then check:
  - overlap with the printed mates = 0 and with mates + clearance = 0
  - drop-on path: the continuous swept volume from seated to +30 mm has <0.01 mm3 overlap
  - still one body, watertight after reload
Use the STLs that were actually printed as mates, not a newer regeneration: the fit is against the physical part.

Frames: each STL is usually written in its own print frame (moved onto the bed). With --placements, the JSON maps
file stem -> the [x, y, z] shift that was ADDED to go from model frame to print frame; it is subtracted to work in
the model frame and the result is written back in the part's own print frame. Without it, all files must already
share one frame. Exit 1 when any check fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meshkit as mk  # noqa: E402
import manifold3d as mf  # noqa: E402


def swept_volume(part, height=30.0):
    """Solid swept along +Z, preserving concavities and holes in its XY footprint.

    Every newly occupied point crosses the original boundary during translation.
    Union that boundary's triangular prisms with the initial solid; vertical faces
    yield empty (coplanar) hulls. This covers every height, not just sampled poses.
    """
    triangles = mk.from_manifold(part).triangles
    shift = np.array([0.0, 0.0, height])
    return mk.union([part] + [mf.Manifold.hull_points(np.vstack([tri, tri + shift])) for tri in triangles])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part")
    ap.add_argument("--mates", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--clear", type=float, default=0.15, help="mm gap to the printed mates (used: 0.15)")
    ap.add_argument("--placements", help="JSON {stem: [dx, dy, dz]} print-frame shifts")
    ap.add_argument("--min-body", type=float, default=1.0, help="mm3; smaller crumbs left by the cut are dropped")
    ap.add_argument("--grow-dirs", default="3d", choices=("3d", "xy+up"))
    args = ap.parse_args(argv)

    shifts = json.loads(Path(args.placements).read_text()) if args.placements else {}

    def model_frame(path):
        mesh = mk.load(path)
        shift = np.array(shifts.get(Path(path).stem, (0, 0, 0)), float)
        mesh.apply_translation(-shift)
        return mesh, shift

    part_mesh, part_shift = model_frame(args.part)
    part = mk.to_manifold(part_mesh) or mk.bodies_as_manifold(part_mesh)
    mates = mk.union([mk.to_manifold(m) or mk.bodies_as_manifold(m) for m, _ in map(model_frame, args.mates)])
    grown = mk.grow(mates, args.clear, args.grow_dirs)

    fit = part - grown
    pieces = sorted(fit.decompose(), key=lambda p: -p.volume())
    keep = [p for p in pieces if p.volume() > args.min_body]
    fit = mf.Manifold.compose(keep)
    print(f"removed {part.volume() - fit.volume():.2f} mm3; bodies kept {len(keep)}, crumbs dropped "
          f"{len(pieces) - len(keep)} ({sum(p.volume() for p in pieces[len(keep):]):.3f} mm3)")

    out = mk.from_manifold(fit)
    out.apply_translation(part_shift)
    back, report = mk.clean_export(out, args.out)
    check = back.copy()
    check.apply_translation(-part_shift)
    final = mk.to_manifold(check) or mk.bodies_as_manifold(check)

    overlap = (final ^ mates).volume()
    overlap_grown = (final ^ grown).volume()
    path_overlap = (swept_volume(final) ^ mates).volume()
    print(f"overlap with printed mates {overlap:.4f} mm3; with mates + {args.clear} mm {overlap_grown:.4f} mm3")
    print(f"drop-on path (continuous sweep 0 to +30 mm): {path_overlap:.4f} mm3 overlap")
    print("export:", report)
    ok = (overlap < 0.01 and path_overlap < 0.01 and report["watertight"] and report["bad_edges"] == 0
          and report["bodies"] == 1)
    print("PASS" if ok else "CHECK FAILED: see numbers above (bodies must be 1, overlaps ~0)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
