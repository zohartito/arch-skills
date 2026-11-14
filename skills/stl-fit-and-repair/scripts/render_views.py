#!/usr/bin/env python3
"""Render STLs to one PNG (iso + front + side + top) so a person can SEE a print fix before it is printed.

    render_views.py A.stl [B.stl ...] --out views.png [--zoom x0 y0 z0 x1 y1 z1] [--max-tris 80000]

Several files are drawn in different colours (e.g. walls grey + new roof white) in their shared frame. --zoom crops
every view to a box in mm (e.g. one railing run) and only draws triangles inside it. Automated "hanging face" tests
were unreliable on real railings (sliver noise); a zoomed render answered "do the pickets reach past the slab?".
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

COLOURS = ["0.85", "#e8d9b0", "#9ec5e8", "#e8a09e", "#b5e8a0"]
VIEWS = {"iso": (28, -55), "looking +Y (from -Y)": (0, -90), "looking -X (from +X)": (0, 0), "top": (90, -90)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--zoom", nargs=6, type=float, metavar=("X0", "Y0", "Z0", "X1", "Y1", "Z1"))
    ap.add_argument("--max-tris", type=int, default=80000)
    args = ap.parse_args(argv)

    meshes = [trimesh.load(p, force="mesh") for p in args.inputs]
    lo = np.min([m.bounds[0] for m in meshes], axis=0)
    hi = np.max([m.bounds[1] for m in meshes], axis=0)
    if args.zoom:
        lo, hi = np.array(args.zoom[:3]), np.array(args.zoom[3:])
    light = np.array([0.4, -0.6, 0.7])
    light /= np.linalg.norm(light)

    fig = plt.figure(figsize=(14, 10))
    for k, (name, (elev, azim)) in enumerate(VIEWS.items()):
        ax = fig.add_subplot(2, 2, k + 1, projection="3d")
        for i, mesh in enumerate(meshes):
            tris = mesh.triangles
            centres = tris.mean(1)
            inside = np.all((centres >= lo) & (centres <= hi), axis=1)
            tris, normals = tris[inside], mesh.face_normals[inside]
            if len(tris) > args.max_tris:
                pick = np.random.default_rng(0).choice(len(tris), args.max_tris, replace=False)
                tris, normals = tris[pick], normals[pick]
            base = np.array(matplotlib.colors.to_rgb(COLOURS[i % len(COLOURS)]))
            shade = (0.45 + 0.55 * np.clip(normals @ light, 0, 1))[:, None] * base
            ax.add_collection3d(Poly3DCollection(tris, facecolors=shade, edgecolors="none"))
        ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
        ax.set_box_aspect(np.maximum(hi - lo, 1e-3))
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(name)
        ax.set_axis_off()
    fig.suptitle("  ".join(f"{COLOURS[i % len(COLOURS)]}: {Path(p).name}" for i, p in enumerate(args.inputs)), fontsize=9)
    fig.tight_layout()
    fig.savefig(args.out, dpi=110)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
