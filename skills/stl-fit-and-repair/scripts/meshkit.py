#!/usr/bin/env python3
"""Mesh toolkit for printable architecture-model parts (STL, mm). Library + CLI.

Used on one architecture studio project (Oct 2026): one-piece roofs, fin bridges, garden screens, repaired cars and scanned figures.
Needs: trimesh, manifold3d, numpy (+ pymeshfix for `repair`, scipy + scikit-image for `solidify`).
Usage: python meshkit.py <command> ...

Commands
  check  IN.stl [...]                      bodies, volumes, watertight, open/non-manifold edges, extents
  repair IN OUT [--max-faces N]            pymeshfix + inside-out fix + manifold rebuild + sit on z=0 + safe export
  weld   IN OUT [--reach 1.2]              fuse bodies that only touch (face/line contact) into one piece with weld beads
  drop-fragments IN OUT [--min 2.0]        delete loose bodies under MIN mm3 (never strut them)
  thicken IN OUT --grow MM                 push every surface out along its normal (paper-thin leaves, fins)
  solidify IN OUT [--pitch 0.07]           fuse OPEN shells (render meshes, car bodies) into one solid on a voxel grid
  export IN OUT                            safe STL export only (zero-volume bodies, twin faces, edge pinches)

Every write goes through clean_export(): the STL is read back from disk and re-verified, because float32 rounding
in STL can turn a valid solid into one with pinched edges that Bambu Studio reports as non-manifold.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh
import manifold3d as mf


# ---------------------------------------------------------------- conversions
def to_manifold(mesh: trimesh.Trimesh):
    """trimesh -> Manifold, or None if it is not a closed, outward-facing solid."""
    m = mf.Manifold(mf.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                            tri_verts=np.asarray(mesh.faces, np.uint32)))
    if m.status() != mf.Error.NoError or m.is_empty() or m.volume() < 0:
        return None
    return m


def from_manifold(m) -> trimesh.Trimesh:
    out = m.to_mesh()
    return trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=False)


def union(manifolds):
    manifolds = [m for m in manifolds if m is not None and not m.is_empty()]
    return mf.Manifold.batch_boolean(manifolds, mf.OpType.Add) if manifolds else mf.Manifold()


def bodies_as_manifold(mesh: trimesh.Trimesh, min_volume: float = 0.05):
    """Split into connected bodies, drop zero-volume slivers, turn inside-out bodies right way out, union the rest."""
    mesh = mesh.copy()
    mesh.merge_vertices()
    keep = []
    for part in mesh.split(only_watertight=False):
        if abs(part.volume) < min_volume:
            continue
        if part.volume < 0:
            part.invert()
        m = mf.Manifold(mf.Mesh(vert_properties=np.asarray(part.vertices, np.float32),
                                tri_verts=np.asarray(part.faces, np.uint32)))
        if m.status() == mf.Error.NoError and not m.is_empty():
            keep.append(m)
    return union(keep)


# ---------------------------------------------------------------- safe export
def edge_report(mesh: trimesh.Trimesh) -> int:
    """Number of edges not shared by exactly two faces (what Bambu Studio calls open / non-manifold edges)."""
    return int((np.unique(mesh.edges_sorted, axis=0, return_counts=True)[1] != 2).sum())


def clean_export(mesh: trimesh.Trimesh, path, filler: float = 0.25, min_body: float = 0.05):
    """Write an STL that stays a valid solid after float32 rounding, and prove it by reading it back.

    - drops zero-volume bodies (< min_body mm3)
    - removes collapsed and back-to-back twin faces (they cancel out)
    - seals edge pinches (two solids touching only along an edge) with tiny `filler` mm sausages, up to 6 rounds
    Returns (reloaded mesh, report dict)."""
    path = Path(path)
    whole = to_manifold(mesh)
    if whole is None:
        whole = bodies_as_manifold(mesh)
    fillers = 0
    final = None
    for _ in range(6):
        whole = mf.Manifold.compose([p for p in whole.decompose() if p.volume() > min_body])
        out = from_manifold(whole)
        merged = trimesh.Trimesh(out.vertices.astype(np.float32).astype(np.float64), out.faces, process=True)
        f = merged.faces
        ok = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
        _, inv, cnt = np.unique(np.sort(f, axis=1), axis=0, return_inverse=True, return_counts=True)
        ok &= cnt[inv.ravel()] != 2
        merged = trimesh.Trimesh(merged.vertices, f[ok], process=False)
        merged.remove_unreferenced_vertices()
        if merged.is_watertight:
            final = merged
            break
        edges, counts = np.unique(merged.edges_sorted, axis=0, return_counts=True)
        h = filler / 2
        cube = np.array([[x, y, z] for x in (-h, h) for y in (-h, h) for z in (-h, h)])
        sausages = [mf.Manifold.hull_points(np.vstack([cube + merged.vertices[a], cube + merged.vertices[b]]))
                    for a, b in edges[counts != 2]]
        fillers += len(sausages)
        whole = union([whole] + sausages)
    if final is None:
        final = from_manifold(whole)
    path.parent.mkdir(parents=True, exist_ok=True)
    final.export(path)
    back = trimesh.load(path, force="mesh")
    check = to_manifold(back) if back.is_watertight else None
    report = {"file": path.name, "watertight": bool(back.is_watertight), "bad_edges": edge_report(back),
              "bodies": count_bodies(check)[0] if check is not None else -1, "faces": len(back.faces),
              "pinch_fillers": fillers, "extents_mm": np.round(back.extents, 2).tolist()}
    return back, report


# ---------------------------------------------------------------- repair
def repair(mesh: trimesh.Trimesh, max_faces: int | None = None, min_fraction: float = 0.001) -> trimesh.Trimesh:
    """Downloaded / scanned / modelled mesh -> valid solid(s), centred in XY and sitting on z = 0.
    Each connected component is handled on its own: kept as is when already a valid solid (inside-out ones flipped),
    otherwise pymeshfix fills holes and removes non-manifold edges. pymeshfix keeps only ONE component per call, so
    calling it on a whole multi-part mesh silently deletes the rest (an agave's 16 leaves became 1 leaf).
    Components smaller than min_fraction of the largest (scan specks) are dropped."""
    import pymeshfix
    if max_faces and len(mesh.faces) > max_faces:
        mesh = mesh.simplify_quadric_decimation(face_count=max_faces)
    mesh = mesh.copy()
    mesh.merge_vertices()
    solids = []
    for part in mesh.split(only_watertight=False):
        if part.is_watertight:
            if part.volume < 0:
                part.invert()
            m = to_manifold(part)
            if m is not None:
                solids.append(m)
                continue
        fix = pymeshfix.MeshFix(np.asarray(part.vertices), np.asarray(part.faces))
        fix.repair(joincomp=True, remove_smallest_components=False)
        if len(fix.faces):
            solids.append(bodies_as_manifold(trimesh.Trimesh(fix.points, fix.faces), 0.0))
    solids = [s for s in solids if not s.is_empty()]
    largest = max((s.volume() for s in solids), default=0.0)
    out = from_manifold(union([s for s in solids if s.volume() >= min_fraction * largest]))
    return place_on_bed(out)


def place_on_bed(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh = mesh.copy()
    mesh.apply_translation(-np.r_[mesh.bounds.mean(0)[:2], mesh.bounds[0][2]])
    return mesh


def drop_fragments(m, min_volume: float = 2.0):
    """Delete loose bodies smaller than min_volume mm3. Rule from use: do NOT tie crumbs on with struts; struts print as
    stray bars that the slicer then supports. Returns (manifold, list of dropped volumes)."""
    pieces = sorted(m.decompose(), key=lambda p: -p.volume())
    keep = [p for p in pieces if p.volume() >= min_volume]
    dropped = [round(p.volume(), 3) for p in pieces if p.volume() < min_volume]
    return mf.Manifold.compose(keep) if keep else mf.Manifold(), dropped


# ---------------------------------------------------------------- one piece
def weld_contacts(solids, reach: float = 1.2, segment: float = 3.0, touch: float = 0.05):
    """Parts that only touch (face or line contact, ~zero overlap) print as separate bodies or hair-thin joints.
    For every touching pair, add a weld bead along the seam: per `segment` mm of seam, the convex hull of both
    surfaces within `reach` mm of it. Returns one Manifold of beads (or None). Seeded: same input, same beads."""
    from scipy.spatial import cKDTree
    meshes = [from_manifold(s) for s in solids]
    samples = [trimesh.sample.sample_surface_even(m, int(max(2000, min(400000, m.area / 0.01))), seed=5)[0]
               for m in meshes]
    beads = []
    for i in range(len(meshes)):
        for j in range(i + 1, len(meshes)):
            a, b = meshes[i], meshes[j]
            if np.any(a.bounds[0] > b.bounds[1] + 0.2) or np.any(b.bounds[0] > a.bounds[1] + 0.2):
                continue
            _, dist, _ = trimesh.proximity.closest_point(b, samples[i])
            seam = samples[i][dist < touch]
            if len(seam) < 50:
                continue
            centre = seam.mean(0)
            axis = np.linalg.svd(seam - centre, full_matrices=False)[2][0]
            t_seam = (seam - centre) @ axis
            tree = cKDTree(seam)
            pool = np.vstack([s[tree.query(s, distance_upper_bound=reach)[0] < reach] for s in (samples[i], samples[j])])
            t_pool = (pool - centre) @ axis
            for t0 in np.arange(t_seam.min(), t_seam.max(), segment):
                sel = pool[(t_pool >= t0 - 0.3) & (t_pool <= t0 + segment + 0.3)]
                if len(sel) < 8:
                    continue
                try:
                    hull = mf.Manifold.hull_points(sel.astype(np.float64))
                except Exception:
                    continue
                if hull.volume() > 0.01:          # flat hulls are not volumes
                    beads.append(hull)
    return union(beads) if beads else None


def grow(m, distance: float, directions: str = "3d"):
    """Approximate outward offset: union of copies translated by `distance` in 14 (3d) or 9 (xy+up) directions.
    Used to grow a printed mate by the fit clearance before subtracting it."""
    if directions == "xy+up":
        dirs = [(0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (.7, .7, 0), (-.7, .7, 0), (.7, -.7, 0), (-.7, -.7, 0)]
    else:
        axis = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        corner = [tuple(np.array((x, y, z)) / np.sqrt(3)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        dirs = axis + corner
    return union([m] + [m.translate(tuple(np.array(d) * distance)) for d in dirs])


# ---------------------------------------------------------------- thin parts
def thicken_offset(mesh: trimesh.Trimesh, grow_mm: float) -> trimesh.Trimesh:
    """Push every vertex out along its normal: a paper-thin leaf gains ~2 x grow_mm. Shape kept; good for plants.
    Values used: 0.12 mm at 1/4", 0.14 mm at 1/8" (0.2 nozzle)."""
    mesh = mesh.copy()
    mesh.merge_vertices()
    mesh.vertices = mesh.vertices + mesh.vertex_normals * grow_mm
    return place_on_bed(mesh)


def triangle_prisms(mesh: trimesh.Trimesh, below: float, above: float):
    """Open surface -> solid sheet: one convex prism per triangle spanning [-below, +above] along its normal, unioned.
    Slow on big meshes; use for fins, panels and blades, not for whole buildings."""
    prisms = []
    for tri, n, area in zip(mesh.triangles, mesh.face_normals, mesh.area_faces):
        if area < 1e-6:
            continue
        hull = mf.Manifold.hull_points(np.vstack([tri - n * below, tri + n * above]).astype(np.float64))
        if hull.volume() > 1e-4:
            prisms.append(hull)
    return union(prisms) if prisms else None


def leaf_thickness(mesh: trimesh.Trimesh, n: int = 1500):
    """10th percentile and median wall thickness (inward ray from sampled surface points)."""
    pts, fid = trimesh.sample.sample_surface(mesh, n, seed=1)
    normals = mesh.face_normals[fid]
    locs, idx, _ = mesh.ray.intersects_location(pts - normals * 1e-3, -normals, multiple_hits=False)
    t = np.linalg.norm(locs - pts[idx], axis=1)
    return float(np.percentile(t, 10)), float(np.median(t))


def voxel_solidify(mesh: trimesh.Trimesh, pitch: float = 0.07, max_faces: int = 120000) -> trimesh.Trimesh:
    """Fuse open render shells (a car body with an open underside, overlapping panels) into ONE solid.
    A voxel is inside when surface lies on both sides of it along >= 5 of the 6 axis directions; then fill holes,
    open (drop whiskers), keep the largest body, marching cubes, Taubin smoothing (removes voxel terracing, keeps
    volume), decimate, pymeshfix. Pitch 0.07 mm worked for a 45 mm car (Ford Focus at 1/8"); cost grows as 1/pitch^3."""
    import pymeshfix
    from scipy import ndimage
    from skimage import measure
    lo = mesh.bounds[0] - 3 * pitch
    dims = np.ceil((mesh.extents + 6 * pitch) / pitch).astype(int)
    surface = np.zeros(dims, bool)
    pts, _ = trimesh.sample.sample_surface_even(mesh, int(mesh.area / (pitch * 0.4) ** 2), seed=1)
    pts = np.vstack([pts, mesh.vertices])
    idx = np.clip(((pts - lo) / pitch).astype(int), 0, dims - 1)
    surface[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    surface = ndimage.binary_dilation(surface, iterations=1)
    votes = np.zeros(dims, np.uint8)
    for axis in range(3):
        fwd = np.maximum.accumulate(surface, axis=axis)
        bwd = np.flip(np.maximum.accumulate(np.flip(surface, axis), axis=axis), axis)
        votes += fwd.astype(np.uint8) + bwd.astype(np.uint8)
    solid = ndimage.binary_fill_holes((votes >= 5) | surface)
    solid = ndimage.binary_opening(solid, iterations=1)
    labels, _ = ndimage.label(solid)
    solid = labels == (np.argmax(np.bincount(labels.ravel())[1:]) + 1)
    verts, faces, _, _ = measure.marching_cubes(np.pad(solid, 1).astype(np.float32), 0.5)
    out = trimesh.Trimesh((verts - 1) * pitch + lo, faces)
    trimesh.smoothing.filter_taubin(out, lamb=0.5, nu=-0.53, iterations=25)
    if len(out.faces) > max_faces:
        out = out.simplify_quadric_decimation(face_count=max_faces)
    fix = pymeshfix.MeshFix(np.asarray(out.vertices), np.asarray(out.faces))
    fix.repair()
    return place_on_bed(from_manifold(bodies_as_manifold(trimesh.Trimesh(fix.points, fix.faces), 1.0)))


# ---------------------------------------------------------------- reporting
def count_bodies(m) -> tuple[int, int]:
    """(real bodies, zero-volume bits). STL float32 rounding can leave harmless zero-volume bits; don't count them."""
    vols = [p.volume() for p in m.decompose()]
    return sum(v > 0.01 for v in vols), sum(v <= 0.01 for v in vols)


def describe(mesh: trimesh.Trimesh) -> dict:
    m = to_manifold(mesh) if mesh.is_watertight else None
    vols = sorted((round(p.volume(), 2) for p in m.decompose() if p.volume() > 0.01), reverse=True) if m is not None else []
    return {"watertight": bool(mesh.is_watertight), "winding_ok": bool(mesh.is_winding_consistent),
            "bad_edges": edge_report(mesh), "valid_solid": m is not None,
            "bodies": len(vols) if m is not None else len(mesh.split(only_watertight=False)),
            "zero_volume_bits": count_bodies(m)[1] if m is not None else None,
            "body_volumes_mm3": vols[:8], "extents_mm": np.round(mesh.extents, 2).tolist(), "faces": len(mesh.faces)}


def load(path) -> trimesh.Trimesh:
    return trimesh.load(path, force="mesh")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("inputs", nargs="+")
    for name in ("repair", "weld", "drop-fragments", "thicken", "solidify", "export"):
        p = sub.add_parser(name)
        p.add_argument("input")
        p.add_argument("output")
        if name == "repair":
            p.add_argument("--max-faces", type=int, default=None)
        if name == "weld":
            p.add_argument("--reach", type=float, default=1.2)
        if name == "drop-fragments":
            p.add_argument("--min", type=float, default=2.0)
        if name == "thicken":
            p.add_argument("--grow", type=float, required=True)
        if name == "solidify":
            p.add_argument("--pitch", type=float, default=0.07)
    args = ap.parse_args(argv)

    if args.cmd == "check":
        ok = True
        for path in args.inputs:
            info = describe(load(path))
            ok &= info["valid_solid"] and info["bad_edges"] == 0
            print(Path(path).name, info)
        return 0 if ok else 1

    mesh = load(args.input)
    if args.cmd == "repair":
        out = repair(mesh, args.max_faces)
    elif args.cmd == "weld":
        parts = [bodies_as_manifold(p) for p in mesh.split(only_watertight=False) if abs(p.volume) > 0.05]
        beads = weld_contacts(parts, reach=args.reach)
        welded = union(parts + ([beads] if beads is not None else []))
        out = from_manifold(welded)
        print(f"bodies in file {len(parts)}, after union + weld beads {count_bodies(welded)[0]}")
    elif args.cmd == "drop-fragments":
        kept, dropped = drop_fragments(bodies_as_manifold(mesh), args.min)
        print(f"dropped {len(dropped)} fragments (mm3): {dropped[:20]}")
        out = from_manifold(kept)
    elif args.cmd == "thicken":
        out = thicken_offset(mesh, args.grow)
        print("leaf thickness 10%% / median: %.2f / %.2f mm" % leaf_thickness(out))
    elif args.cmd == "solidify":
        out = voxel_solidify(mesh, args.pitch)
    else:
        out = mesh
    _, report = clean_export(out, args.output)
    print(report)
    return 0 if report["watertight"] and report["bad_edges"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
