#!/usr/bin/env python3
"""Downloaded entourage (people, pets, cars, plants, furniture) -> repaired STLs at true model scale + an unbounded combined row STL.

    prep_entourage.py spec.csv --src downloads/ --mmft 6.35 --out prepped/1-4in --plate pets-plate_1-4in.stl [--gap 3]

spec.csv columns (one row per item; blank = default):
  name        output basename (no path separators)           e.g. cat-sitting
  file        relative file beneath --src (STL, OBJ, 3MF)    e.g. cat-sitting__Cat.obj
  size_ft     real size in feet ...                         e.g. 0.95
  dim         ... measured as h (height) or w (largest plan dimension)
  source_scale  instead of size_ft: the file is already a scale figure at 1:N (e.g. 50 for 1:50 people);
              it is rescaled N / (304.8 / mmft), so 1:50 -> 1/4" (1:48) is x 50/48
  rot_x       degrees about X to stand it up (Y-up downloads: 90)
  cut_base    1 = cut off a round display base (detected where the cross-section shrinks below 35 % of the disc)
  grow_mm     push surfaces out this much (paper-thin leaves: 0.12 at 1/4", 0.14 at 1/8")
  max_faces   decimate above this (default 60000; keeps a plate under ~20 MB)

Every item is repaired (pymeshfix + manifold rebuild + safe export) so Bambu Studio shows no open edges; the
report gives each printed size in mm and the real size it represents, so a wrong-size dog is caught here.
Needs stl-fit-and-repair/scripts/meshkit.py (found automatically next to this skill).
Specification paths must not use traversal, absolute paths or symlinks. Existing output files
are refused; select a new output folder/plate filename for another run.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "stl-fit-and-repair" / "scripts"))
import meshkit as mk  # noqa: E402


def spec_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts or any(c in value for c in "\\:\0\r\n"):
        raise ValueError("specification path must stay relative to its selected root")
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("specification path must be contained and must not use symlinks")
    return path


def export_new(mesh, target: Path):
    """Repair/export in scratch, then exclusively create the requested output."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        temporary = Path(folder) / target.name
        back, report = mk.clean_export(mesh, temporary)
        with temporary.open("rb") as source, target.open("xb") as dest:
            shutil.copyfileobj(source, dest)
    return back, report


def base_top(mesh: trimesh.Trimesh):
    """z where a round display base ends: the horizontal section shrinks below 35 % of the base area."""
    z0, z1 = mesh.bounds[0][2], mesh.bounds[0][2] + 0.4 * mesh.extents[2]
    base_area = None
    for z in np.arange(z0 + 0.2, z1, 0.1):
        sec = mesh.section(plane_origin=(0, 0, z), plane_normal=(0, 0, 1))
        if sec is None:
            continue
        try:
            area = sum(p.area for p in sec.to_2D()[0].polygons_full)
        except Exception:
            continue
        if base_area is None:
            base_area = area
        elif area < 0.35 * base_area:
            return float(z)
    return None


def prep_item(row: dict, src: Path, mmft: float):
    mesh = trimesh.load(spec_path(src, row["file"]), force="mesh")
    if float(row.get("rot_x") or 0):
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(float(row["rot_x"])), [1, 0, 0]))
    max_faces = int(row.get("max_faces") or 60000)
    if len(mesh.faces) > max_faces:
        mesh = mesh.simplify_quadric_decimation(face_count=max_faces)
    cut = base_top(mesh) if row.get("cut_base", "").strip() in ("1", "yes", "true") else None
    solid = mk.repair(mesh)                                                 # re-seated on z = 0
    if cut is not None:
        z_cut = cut - mesh.bounds[0][2] + 0.2                               # 0.2 mm above the base clears its rim
        m = mk.to_manifold(solid) or mk.bodies_as_manifold(solid)
        solid = mk.place_on_bed(mk.from_manifold(m.trim_by_plane((0.0, 0.0, 1.0), float(z_cut))))
    if row.get("source_scale"):
        factor = float(row["source_scale"]) / (304.8 / mmft)
    else:
        ref = solid.extents[2] if row.get("dim", "h").strip() == "h" else max(solid.extents[:2])
        factor = float(row["size_ft"]) * mmft / ref
    solid.apply_scale(factor)
    if float(row.get("grow_mm") or 0):
        solid = mk.thicken_offset(solid, float(row["grow_mm"]))
    return mk.place_on_bed(solid), cut


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--src", required=True)
    ap.add_argument("--mmft", type=float, required=True, help="mm per real foot: 1/4in 6.35, 1/8in 3.175, 1/16in 1.5875")
    ap.add_argument("--out", required=True)
    ap.add_argument("--plate", help="also write an unbounded row STL; arrange/split in the slicer (no bed-fit check)")
    ap.add_argument("--gap", type=float, default=3.0, help="mm between items on the plate")
    args = ap.parse_args(argv)

    out = Path(args.out)
    rows = list(csv.DictReader(open(args.spec)))
    targets = []
    for row in rows:
        name = row["name"]
        if not name or name in (".", "..") or any(c in name for c in "/\\:\0\r\n"):
            raise ValueError("output name must be a safe basename")
        spec_path(Path(args.src), row["file"])
        targets.append(spec_path(out, f"{name}.stl"))
    if args.plate:
        plate_path = Path(args.plate).absolute()
        targets.append(spec_path(plate_path.parent, plate_path.name))
    if len({p.resolve() for p in targets}) != len(targets):
        raise ValueError("duplicate output names")
    for target in targets:
        if target.exists():
            raise FileExistsError(f"output already exists: {target.name}; choose a new path")
    items, ok = [], True
    for row in rows:
        solid, cut = prep_item(row, Path(args.src), args.mmft)
        back, report = export_new(solid, spec_path(out, f"{row['name']}.stl"))
        ok &= report["watertight"] and report["bad_edges"] == 0
        h_ft, w_ft = back.extents[2] / args.mmft, max(back.extents[:2]) / args.mmft
        print(f"{row['name']:26s} {np.round(back.extents, 1).tolist()} mm = {h_ft:.1f} ft tall, {w_ft:.1f} ft long"
              f"{'' if cut is None else ', display base cut'}; bodies {report['bodies']}, bad edges {report['bad_edges']}")
        items.append(back)

    if args.plate and items:
        placed, x = [], 0.0
        for t in items:
            t = t.copy()
            if t.extents[1] > t.extents[0] * 1.5:          # lay long items along X so the plate stays compact
                t.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
            t.apply_translation((x - t.bounds[0][0], -t.bounds.mean(0)[1], -t.bounds[0][2]))
            placed.append(t)
            x += t.extents[0] + args.gap
        plate = trimesh.util.concatenate(placed)
        plate.apply_translation(-np.r_[plate.bounds.mean(0)[:2], 0])
        back, report = export_new(plate, spec_path(plate_path.parent, plate_path.name))
        ok &= report["watertight"] and report["bad_edges"] == 0
        size_mb = Path(args.plate).stat().st_size / 1e6
        print(f"plate {Path(args.plate).name}: {np.round(back.extents, 1).tolist()} mm, {report['bodies']} bodies, "
              f"bad edges {report['bad_edges']}, {size_mb:.1f} MB{'  (over 30 MB: lower max_faces)' if size_mb > 30 else ''}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
