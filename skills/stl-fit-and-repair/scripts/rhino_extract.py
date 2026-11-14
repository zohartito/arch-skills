#!/usr/bin/env python3
"""Pull objects out of a SAVED Rhino .3dm (read-only, via rhino3dm) as print-scale trimesh solids in mm.

    rhino_extract.py MODEL.3dm --layer "07 STAIRS AND GUARDS" [--name-contains picket] [--mmft 3.175]
        [--include-hidden] [--sha-prefix 1a2b3c4d] --out part.stl

Library use:  from rhino_extract import open_model, iter_objects, object_mesh

Rules this encodes (from one studio project's model prints):
- Never open or save the live Rhino doc; read the saved file and record its SHA-256 (printed).
- Visible = object visible AND every parent layer visible. Hidden objects are skipped unless --include-hidden
  (e.g. alternate states such as open/closed fins that are hidden in the model but still printed).
- Model units are feet; mm per model foot = 304.8 / scale denominator in inches (1/8" -> 3.175, 1/4" -> 6.35).
- Objects saved without a render mesh (never displayed, typically hidden ones) get the convex hull of their
  Brep vertices. That is exact for flat plates and boxes and WRONG for curved or L-shaped parts: the report lists
  every hull fallback so you can check them.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import sys
from pathlib import Path

import numpy as np
import rhino3dm
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))


def open_model(path, sha_prefix: str | None = None):
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha_prefix and not sha.startswith(tuple(sha_prefix.split(","))):
        raise SystemExit(f"model sha {sha[:16]} does not start with {sha_prefix}: wrong or changed file")
    return rhino3dm.File3dm.Read(str(path)), sha


def layer_paths(model):
    layers = list(model.Layers)
    by_id = {str(layer.Id): layer for layer in layers}

    def visible(layer):
        while layer is not None:
            if not layer.Visible:
                return False
            layer = by_id.get(str(layer.ParentLayerId))
        return True
    return {i: (layer.FullPath, visible(layer)) for i, layer in enumerate(layers)}


def iter_objects(model, layer_prefix: str = "", name_contains: str = "", include_hidden: bool = False):
    paths = layer_paths(model)
    for obj in model.Objects:
        path, layer_on = paths[obj.Attributes.LayerIndex]
        name = obj.Attributes.Name or ""
        if layer_prefix and not path.startswith(layer_prefix):
            continue
        if name_contains and name_contains.lower() not in name.lower():
            continue
        if not include_hidden and not (obj.Attributes.Visible and layer_on):
            continue
        yield obj, path, name


def _rhino_mesh(rm, mmft):
    v = np.array([(rm.Vertices[i].X, rm.Vertices[i].Y, rm.Vertices[i].Z) for i in range(len(rm.Vertices))])
    tris = []
    for i in range(len(rm.Faces)):
        a, b, c, d = rm.Faces[i]
        tris.append((a, b, c))
        if c != d:
            tris.append((a, c, d))
    return trimesh.Trimesh(v * mmft, np.array(tris).reshape(-1, 3), process=False)


def _brep_points(geometry):
    brep = geometry.ToBrep() if isinstance(geometry, rhino3dm.Extrusion) else geometry
    if not isinstance(brep, rhino3dm.Brep):
        return None
    pts = [(v.Location.X, v.Location.Y, v.Location.Z) for v in brep.Vertices]
    return np.array(pts) if len(pts) >= 4 else None


def object_mesh(geometry, mmft: float):
    """Return (trimesh in mm or None, how): how is 'render', 'mesh', 'hull' or 'none'."""
    if isinstance(geometry, rhino3dm.Mesh):
        return _rhino_mesh(geometry, mmft), "mesh"
    if isinstance(geometry, rhino3dm.Extrusion):
        sources = [geometry.GetMesh(rhino3dm.MeshType.Render)]
    elif isinstance(geometry, rhino3dm.Brep):
        sources = [face.GetMesh(rhino3dm.MeshType.Render) for face in geometry.Faces]
    else:
        return None, "none"
    parts = [_rhino_mesh(s, mmft) for s in sources if s is not None and len(s.Faces)]
    if parts and len(parts) == len(sources):
        mesh = trimesh.util.concatenate(parts)
        mesh.merge_vertices()
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        return mesh, "render"
    pts = _brep_points(geometry)
    if pts is None:
        return None, "none"
    return trimesh.convex.convex_hull(pts * mmft), "hull"


def main(argv=None) -> int:
    import meshkit as mk
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model")
    ap.add_argument("--layer", default="", help="full layer path prefix, e.g. 'PARENT::CHILD'")
    ap.add_argument("--name-contains", default="")
    ap.add_argument("--mmft", type=float, default=3.175, help="mm per model foot (1/8in = 3.175, 1/4in = 6.35)")
    ap.add_argument("--include-hidden", action="store_true")
    ap.add_argument("--sha-prefix", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    model, sha = open_model(args.model, args.sha_prefix)
    print(f"model {Path(args.model).name} sha256 {sha}")
    meshes, how = [], collections.Counter()
    hulls = []
    for obj, path, name in iter_objects(model, args.layer, args.name_contains, args.include_hidden):
        mesh, kind = object_mesh(obj.Geometry, args.mmft)
        how[kind] += 1
        if mesh is None:
            continue
        if kind == "hull":
            hulls.append(f"{path} :: {name or obj.Attributes.Id}")
        meshes.append(mesh)
    print("objects:", dict(how))
    for h in hulls:
        print("  hull fallback (check it is a flat/convex part):", h)
    if not meshes:
        print("nothing matched")
        return 1
    whole = mk.union([mk.to_manifold(m) or mk.bodies_as_manifold(m) for m in meshes])
    _, report = mk.clean_export(mk.from_manifold(whole), args.out)
    print(report)
    return 0 if report["watertight"] else 1


if __name__ == "__main__":
    sys.exit(main())
