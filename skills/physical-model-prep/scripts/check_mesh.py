#!/usr/bin/env python3
"""Pre-print STL check: watertight, winding, bodies, volume, bounding box (mm), bed fit, thin walls.

Needs trimesh (+ rtree or embreex for the thin-wall rays). Example:
    python check_mesh.py part.stl [...] --min-wall 0.6 --bed 256

STL units are assumed to be millimetres. Exit code 1 if any file is not watertight, has
inconsistent winding or does not fit the bed (and, with --strict-thin, has thin-wall samples).
Thin walls are estimated by casting a ray inward along the normal from sampled surface points.
Sharp wedges, chamfers and small proud ribs also read thin, so thin walls are a WARNING with
example coordinates to inspect in the slicer preview, not an automatic failure.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh


def split_bodies(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    """Connected bodies via union-find on shared vertices (trimesh.split needs scipy/networkx)."""
    parent = np.arange(len(mesh.vertices))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, c in mesh.faces:
        ra, rb, rc = root(a), root(b), root(c)
        parent[rb] = ra
        parent[rc] = ra
    face_roots = np.array([root(face[0]) for face in mesh.faces])
    groups = [np.flatnonzero(face_roots == r) for r in np.unique(face_roots)]
    return mesh.submesh(groups, append=False) if len(groups) > 1 else [mesh]


def thin_samples(mesh: trimesh.Trimesh, min_wall: float, samples: int) -> tuple[float, float, np.ndarray]:
    """(fraction of samples under min_wall, 5th-percentile thickness, the 3 thinnest sample points)."""
    points, face_index = trimesh.sample.sample_surface(mesh, samples, seed=0)
    thickness = trimesh.proximity.thickness(mesh, points, exterior=False,
                                            normals=mesh.face_normals[face_index], method="ray")
    finite = np.isfinite(thickness)
    points, thickness = points[finite], thickness[finite]
    if thickness.size == 0:
        return 0.0, float("nan"), np.empty((0, 3))
    order = np.argsort(thickness)
    worst = points[order[:3]][thickness[order[:3]] < min_wall]
    return float((thickness < min_wall).mean()), float(np.percentile(thickness, 5)), worst


def check(path: Path, min_wall: float, bed: float | None, samples: int, strict_thin: bool) -> bool:
    mesh = trimesh.load(path, force="mesh")
    extents = mesh.bounding_box.extents
    bodies = split_bodies(mesh)
    degenerate = int((~mesh.nondegenerate_faces(height=1e-9)).sum())
    ok = bool(mesh.is_watertight and mesh.is_winding_consistent)
    volume = f"{mesh.volume / 1000:.2f} cm3" if mesh.is_watertight else "n/a (open mesh)"
    print(path.name)
    print(f"  watertight {mesh.is_watertight}, winding consistent {mesh.is_winding_consistent}, "
          f"bodies {len(bodies)}, triangles {len(mesh.faces)}, zero-area faces {degenerate}")
    print(f"  bbox {extents[0]:.2f} x {extents[1]:.2f} x {extents[2]:.2f} mm, volume {volume}, "
          f"z min {mesh.bounds[0][2]:.3f}")
    tiny = [body for body in bodies if body.is_watertight and abs(body.volume) < 0.05]
    if tiny:
        print(f"  WARN {len(tiny)} sliver bodies under 0.05 mm3 (drop them before printing)")
    if degenerate:
        print("  WARN zero-area faces (often float32 STL rounding): drop them, re-export, re-check watertight")
    if bed is not None:
        fits = bool(np.all(extents <= bed))
        ok &= fits
        print(f"  fits {bed:.0f} mm bed as placed: {fits}")
    if mesh.is_watertight and min_wall > 0:
        fraction, p5, worst = thin_samples(mesh, min_wall, samples)
        print(f"  thin wall: {fraction * 100:.1f}% of {samples} samples under {min_wall} mm (5th pct {p5:.2f} mm)")
        if fraction > 0:
            where = "; ".join(f"({x:.1f}, {y:.1f}, {z:.1f})" for x, y, z in worst)
            print(f"  WARN thin spots, e.g. at {where} mm: thicken to >= {min_wall} mm, or confirm they are "
                  f"intended (sheet parts, wedge tips, ribs) in the slicer preview")
            if strict_thin:
                ok = False
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stls", nargs="+", type=Path)
    parser.add_argument("--min-wall", type=float, default=0.6, help="mm; 0 disables the thin-wall check")
    parser.add_argument("--bed", type=float, default=256.0, help="cube bed side in mm; 0 disables")
    parser.add_argument("--samples", type=int, default=3000)
    parser.add_argument("--strict-thin", action="store_true", help="fail (exit 1) on any thin-wall sample")
    args = parser.parse_args()
    results = [check(p, args.min_wall, args.bed or None, args.samples, args.strict_thin) for p in args.stls]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
