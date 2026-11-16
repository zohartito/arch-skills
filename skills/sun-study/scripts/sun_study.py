#!/usr/bin/env python3
"""Headless direct-sun-hours and sun-path study (Ladybug sun positions + trimesh ray casting).

Run with a Python that has requirements-arch-tools.txt installed. See ../SKILL.md for usage.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SITE_PRESETS = {
    # name: (latitude, longitude, standard-time UTC offset in hours)
    "los-angeles-ca": (34.052, -118.244, -8.0),
}

# Meters per model unit, keyed by rhino3dm.UnitSystem name (also accepted by --units).
UNIT_TO_METERS = {
    "Millimeters": 0.001,
    "Centimeters": 0.01,
    "Decimeters": 0.1,
    "Meters": 1.0,
    "Kilometers": 1000.0,
    "Inches": 0.0254,
    "Feet": 0.3048,
    "Yards": 0.9144,
    "Miles": 1609.344,
}
UNIT_ALIASES = {"mm": "Millimeters", "cm": "Centimeters", "m": "Meters", "km": "Kilometers",
                "in": "Inches", "ft": "Feet", "yd": "Yards"}

REFERENCE_YEAR = 2017  # non-leap; Ladybug's default year
CAST_CHUNK = 2_000_000  # rays per intersects_any call
FOOTPRINT_MAX_TRIANGLES = 200_000  # skip the plan overlay on heavier meshes (plot speed)


# ---------------------------------------------------------------- location & time

@dataclass
class Site:
    name: str
    latitude: float
    longitude: float
    time_zone: float
    source: str


def resolve_site(args) -> Site:
    if args.epw:
        from ladybug.epw import EPW
        location = EPW(args.epw).location
        return Site(location.city or Path(args.epw).stem, location.latitude,
                    location.longitude, location.time_zone, f"epw:{args.epw}")
    if args.site:
        lat, lon, tz = SITE_PRESETS[args.site]
        return Site(args.site, lat, lon, tz, "preset")
    if None in (args.lat, args.lon, args.tz):
        raise SystemExit("Location required: --site, --epw, or all of --lat --lon --tz")
    return Site("custom", args.lat, args.lon, args.tz, "lat/lon/tz")


def parse_month_day(text: str) -> date:
    month, day = (int(part) for part in text.split("-"))
    return date(REFERENCE_YEAR, month, day)


def date_range(start: date, end: date) -> list[date]:
    """Inclusive day list; wraps across New Year when end < start (e.g. 11-01 to 02-28)."""
    if end < start:
        end = end.replace(year=REFERENCE_YEAR + 1)
    days = []
    current = start
    while current <= end:
        days.append(current.replace(year=REFERENCE_YEAR))
        current += timedelta(days=1)
    return days


def parse_hours(text: str) -> tuple[float, float]:
    start, end = (float(part) for part in text.split("-"))
    if not 0 <= start < end <= 24:
        raise SystemExit(f"--hours must be like 8-16 within 0-24, got {text!r}")
    return start, end


def timestep_hours(hour_start: float, hour_end: float, step_min: float) -> list[float]:
    """Midpoints of step-length intervals covering [hour_start, hour_end)."""
    if not np.isfinite(step_min) or step_min <= 0:
        raise SystemExit("--step-min must be positive and divide the selected hours window")
    step_h = step_min / 60.0
    intervals = (hour_end - hour_start) / step_h
    count = int(round(intervals))
    if count < 1 or not np.isclose(intervals, count, rtol=0, atol=1e-9):
        raise SystemExit("--step-min must divide the selected hours window exactly")
    return [hour_start + (index + 0.5) * step_h for index in range(count)]


@dataclass
class SunSample:
    day: date
    hour: float
    altitude: float
    azimuth: float
    vector: tuple[float, float, float]  # unit vector pointing TOWARD the sun


def sun_samples(site: Site, days: list[date], hours: list[float], north_deg: float = 0.0,
                daylight_only: bool = True) -> list[SunSample]:
    from ladybug.sunpath import Sunpath
    sunpath = Sunpath(site.latitude, site.longitude, site.time_zone, north_angle=north_deg)
    samples = []
    for day in days:
        for hour in hours:
            sun = sunpath.calculate_sun(day.month, day.day, hour)
            if daylight_only and sun.altitude <= 0:
                continue
            to_sun = sun.sun_vector_reversed
            samples.append(SunSample(day, hour, sun.altitude, sun.azimuth,
                                     (to_sun.x, to_sun.y, to_sun.z)))
    return samples


# ---------------------------------------------------------------- geometry loading

@dataclass
class GeometryStats:
    source: str = ""
    unit_system: str = "Meters"
    to_meters: float = 1.0
    objects_total: int = 0
    objects_considered: int = 0
    objects_meshed: int = 0
    objects_no_mesh: int = 0
    no_mesh_types: dict = field(default_factory=dict)
    objects_hidden_skipped: int = 0
    objects_off_layer_skipped: int = 0
    block_instances: int = 0
    triangles: int = 0
    bounds_m: list | None = None
    warnings: list = field(default_factory=list)


def unit_scale(unit_name: str) -> float:
    canonical = UNIT_ALIASES.get(unit_name.lower(), unit_name.capitalize())
    if canonical not in UNIT_TO_METERS and f"{canonical}s" in UNIT_TO_METERS:
        canonical += "s"
    if canonical not in UNIT_TO_METERS:
        raise SystemExit(f"Unsupported unit {unit_name!r}; use one of {sorted(UNIT_TO_METERS)}")
    return UNIT_TO_METERS[canonical]


def rhino_mesh_to_arrays(mesh) -> tuple[np.ndarray, np.ndarray]:
    vertices = np.array([[point.X, point.Y, point.Z] for point in mesh.Vertices], dtype=float)
    triangles = []
    for index in range(mesh.Faces.Count):
        a, b, c, d = mesh.Faces[index]
        triangles.append((a, b, c))
        if c != d:
            triangles.append((a, c, d))
    return vertices, np.array(triangles, dtype=np.int64).reshape(-1, 3)


def xform_to_matrix(xform) -> np.ndarray:
    return np.array([[getattr(xform, f"M{row}{col}") for col in range(4)] for row in range(4)])


def geometry_meshes(geometry) -> list | None:
    """Return rhino3dm meshes stored on the geometry, or None if it carries none."""
    import rhino3dm
    if isinstance(geometry, rhino3dm.Mesh):
        return [geometry]
    if isinstance(geometry, rhino3dm.Extrusion):
        mesh = geometry.GetMesh(rhino3dm.MeshType.Render) or geometry.GetMesh(rhino3dm.MeshType.Any)
        return [mesh] if mesh else None
    if isinstance(geometry, rhino3dm.Brep):
        meshes = []
        for face_index in range(len(geometry.Faces)):
            face = geometry.Faces[face_index]
            mesh = face.GetMesh(rhino3dm.MeshType.Render) or face.GetMesh(rhino3dm.MeshType.Any)
            if mesh:
                meshes.append(mesh)
        return meshes or None
    return None


MESHABLE_TYPES = ("Brep", "Extrusion", "Mesh", "SubD", "Surface", "InstanceReference")


def layer_paths(model) -> list[str]:
    return [model.Layers[index].FullPath for index in range(len(model.Layers))]


def layers_on(model) -> list[bool]:
    """A layer counts as on only if it and every parent layer are visible."""
    visible_by_path = {model.Layers[i].FullPath: model.Layers[i].Visible
                       for i in range(len(model.Layers))}
    result = []
    for path in layer_paths(model):
        parts = path.split("::")
        prefixes = ["::".join(parts[:depth]) for depth in range(1, len(parts) + 1)]
        result.append(all(visible_by_path.get(prefix, True) for prefix in prefixes))
    return result


def load_3dm(path: Path, layer_filters: list[str] | None, stats: GeometryStats,
             include_off_layers: bool = False):
    """Collect triangles (model units) from a .3dm; expands block instances."""
    import rhino3dm
    model = rhino3dm.File3dm.Read(str(path))
    if model is None:
        raise SystemExit(f"rhino3dm could not read {path}")
    unit_name = str(model.Settings.ModelUnitSystem).split(".")[-1]
    stats.unit_system = unit_name
    if unit_name in UNIT_TO_METERS:
        stats.to_meters = UNIT_TO_METERS[unit_name]
    else:
        stats.warnings.append(f"Model unit system {unit_name} not mapped; assuming meters")
    paths = layer_paths(model)
    on_flags = layers_on(model)
    objects_by_id = {str(obj.Attributes.Id): obj for obj in model.Objects}

    vertex_chunks, face_chunks = [], []
    vertex_offset = 0

    def add_mesh(mesh, matrix):
        nonlocal vertex_offset
        vertices, faces = rhino_mesh_to_arrays(mesh)
        if len(faces) == 0:
            return False
        if matrix is not None:
            homogeneous = np.c_[vertices, np.ones(len(vertices))]
            vertices = (homogeneous @ matrix.T)[:, :3]
        vertex_chunks.append(vertices)
        face_chunks.append(faces + vertex_offset)
        vertex_offset += len(vertices)
        return True

    def add_geometry(geometry, matrix, depth=0) -> bool:
        if isinstance(geometry, rhino3dm.InstanceReference):
            if depth > 8:
                return False
            stats.block_instances += 1
            definition = model.InstanceDefinitions.FindId(geometry.ParentIdefId)
            if definition is None:
                return False
            local = xform_to_matrix(geometry.Xform)
            combined = local if matrix is None else matrix @ local
            any_added = False
            for member_id in definition.GetObjectIds():
                member = objects_by_id.get(str(member_id))
                if member is None:
                    continue
                # Respect saved visibility at every block depth (SKL-08).
                if not member.Attributes.Visible:
                    stats.objects_hidden_skipped += 1
                    continue
                member_layer = member.Attributes.LayerIndex
                if (0 <= member_layer < len(paths) and not on_flags[member_layer]
                        and not include_off_layers):
                    stats.objects_off_layer_skipped += 1
                    continue
                any_added |= add_geometry(member.Geometry, combined, depth + 1)
            return any_added
        meshes = geometry_meshes(geometry)
        if not meshes:
            return False
        return any([add_mesh(mesh, matrix) for mesh in meshes])

    for obj in model.Objects:
        stats.objects_total += 1
        attributes = obj.Attributes
        if attributes.IsInstanceDefinitionObject:
            continue
        geometry = obj.Geometry
        type_name = type(geometry).__name__
        if type_name not in MESHABLE_TYPES:
            continue  # curves, points, annotations, etc. cast no shadow
        valid_layer = 0 <= attributes.LayerIndex < len(paths)
        layer = paths[attributes.LayerIndex] if valid_layer else ""
        if layer_filters and not any(token.lower() in layer.lower() for token in layer_filters):
            continue
        if valid_layer and not on_flags[attributes.LayerIndex] and not include_off_layers:
            stats.objects_off_layer_skipped += 1
            continue
        if not attributes.Visible:
            stats.objects_hidden_skipped += 1
            continue
        stats.objects_considered += 1
        if add_geometry(geometry, None):
            stats.objects_meshed += 1
        else:
            stats.objects_no_mesh += 1
            stats.no_mesh_types[type_name] = stats.no_mesh_types.get(type_name, 0) + 1

    if stats.objects_hidden_skipped or stats.objects_off_layer_skipped:
        stats.warnings.append(
            f"Skipped {stats.objects_hidden_skipped} hidden object(s) and "
            f"{stats.objects_off_layer_skipped} on off layer(s) (saved visibility state); "
            "hidden objects always stay out; --include-off-layers adds off layers.")
    if stats.objects_no_mesh:
        stats.warnings.append(
            f"{stats.objects_no_mesh} object(s) had no stored render mesh and were ignored "
            f"({stats.no_mesh_types}). Re-save from Rhino with shaded/rendered display, or "
            "run Rhino's Mesh/ExtractRenderMesh, to include them.")
    if not vertex_chunks:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), model
    return np.vstack(vertex_chunks), np.vstack(face_chunks), model


def load_context(path: Path, layer_filters, units: str | None, include_off_layers=False):
    """Return (trimesh.Trimesh in meters or None, GeometryStats, rhino3dm model or None)."""
    import trimesh
    stats = GeometryStats(source=str(path))
    model = None
    suffix = path.suffix.lower()
    if suffix == ".3dm":
        vertices, faces, model = load_3dm(path, layer_filters, stats, include_off_layers)
        if units:
            stats.warnings.append(f"--units {units} overrides model unit {stats.unit_system}")
            stats.to_meters = unit_scale(units)
    elif suffix in (".stl", ".obj", ".ply"):
        loaded = trimesh.load(str(path), force="mesh")
        vertices, faces = np.asarray(loaded.vertices), np.asarray(loaded.faces)
        stats.unit_system = units or "Meters"
        stats.to_meters = unit_scale(units) if units else 1.0
        stats.objects_total = stats.objects_considered = stats.objects_meshed = 1
    else:
        raise SystemExit(f"Unsupported geometry format {suffix}; use .3dm, .stl, .obj or .ply")
    if len(faces) == 0:
        stats.warnings.append("No usable mesh geometry found; analysis treats the site as open")
        return None, stats, model
    mesh = trimesh.Trimesh(vertices=vertices * stats.to_meters, faces=faces, process=False)
    stats.triangles = int(len(mesh.faces))
    stats.bounds_m = np.round(mesh.bounds, 3).tolist()
    return mesh, stats, model


# ---------------------------------------------------------------- analysis grid

def rect_grid(x0, y0, x1, y1, z, spacing) -> np.ndarray:
    """Cell-centred grid points (same units as inputs)."""
    xs = np.arange(min(x0, x1) + spacing / 2, max(x0, x1), spacing)
    ys = np.arange(min(y0, y1) + spacing / 2, max(y0, y1), spacing)
    grid_x, grid_y = np.meshgrid(xs, ys)
    return np.c_[grid_x.ravel(), grid_y.ravel(), np.full(grid_x.size, float(z))]


def curve_polygon_points(curve, samples=200) -> np.ndarray:
    polyline = curve.TryGetPolyline()  # rhino3dm returns a Polyline or None
    if polyline is not None and polyline.Count >= 3:
        return np.array([[pt.X, pt.Y, pt.Z] for pt in (polyline[i] for i in range(polyline.Count))])
    domain = curve.Domain
    params = np.linspace(domain.T0, domain.T1, samples)
    return np.array([[pt.X, pt.Y, pt.Z] for pt in (curve.PointAt(t) for t in params)])


def grid_from_layer(model, layer_name: str, spacing_model: float, to_meters: float,
                    z_override_model: float | None) -> tuple[np.ndarray, list[str]]:
    """Grid points (meters) inside closed curves, or on top of surfaces/meshes, on one layer."""
    import rhino3dm
    import trimesh
    from shapely.geometry import Point, Polygon

    notes = []
    paths = layer_paths(model)
    matches = [i for i, p in enumerate(paths)
               if p.lower() == layer_name.lower() or p.split("::")[-1].lower() == layer_name.lower()]
    if not matches:
        raise SystemExit(f"Layer {layer_name!r} not found. Layers: {paths[:40]}")
    point_sets = []
    for obj in model.Objects:
        if obj.Attributes.LayerIndex not in matches:
            continue
        geometry = obj.Geometry
        if isinstance(geometry, rhino3dm.Curve):
            if not geometry.IsClosed:
                notes.append("skipped open curve on grid layer")
                continue
            outline = curve_polygon_points(geometry)
            polygon = Polygon(outline[:, :2])
            if not polygon.is_valid or polygon.area == 0:
                notes.append("skipped invalid/degenerate closed curve on grid layer")
                continue
            z = z_override_model if z_override_model is not None else float(outline[:, 2].mean())
            minx, miny, maxx, maxy = polygon.bounds
            candidates = rect_grid(minx, miny, maxx, maxy, z, spacing_model)
            inside = [polygon.contains(Point(x, y)) for x, y, _ in candidates]
            point_sets.append(candidates[np.array(inside, dtype=bool)])
            continue
        meshes = geometry_meshes(geometry)
        if not meshes:
            notes.append(f"skipped {type(geometry).__name__} without render mesh on grid layer")
            continue
        for mesh in meshes:
            vertices, faces = rhino_mesh_to_arrays(mesh)
            surface = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            (minx, miny, minz), (maxx, maxy, maxz) = surface.bounds
            candidates = rect_grid(minx, miny, maxx, maxy, maxz + 1.0, spacing_model)
            if len(candidates) == 0:
                continue
            down = np.tile([0.0, 0.0, -1.0], (len(candidates), 1))
            locations, ray_index, _ = surface.ray.intersects_location(
                candidates, down, multiple_hits=False)
            hits = candidates[ray_index].copy()
            hits[:, 2] = locations[:, 2] if z_override_model is None else z_override_model
            point_sets.append(hits)
    if not point_sets or sum(len(s) for s in point_sets) == 0:
        raise SystemExit(f"No grid points generated from layer {layer_name!r}: {notes}")
    return np.vstack(point_sets) * to_meters, notes


# ---------------------------------------------------------------- ray casting

def direct_sun_hours(points_m: np.ndarray, sun_vectors: np.ndarray, step_hours: float,
                     context_mesh, offset_m: float = 0.01) -> np.ndarray:
    """Hours of unobstructed direct sun per point. sun_vectors point toward the sun."""
    lit_counts = np.zeros(len(points_m), dtype=np.int64)
    if len(sun_vectors) == 0:
        return lit_counts.astype(float)
    if context_mesh is None:
        return np.full(len(points_m), len(sun_vectors) * step_hours)
    # Embree works in float32: recentre near the origin so far-from-origin models keep precision.
    centre = context_mesh.bounds.mean(axis=0)
    context_mesh = context_mesh.copy()
    context_mesh.apply_translation(-centre)
    origins = points_m - centre + np.array([0.0, 0.0, offset_m])
    vectors_per_chunk = max(1, CAST_CHUNK // max(1, len(points_m)))
    for start in range(0, len(sun_vectors), vectors_per_chunk):
        chunk = sun_vectors[start:start + vectors_per_chunk]
        ray_origins = np.tile(origins, (len(chunk), 1))
        ray_dirs = np.repeat(chunk, len(points_m), axis=0)
        blocked = context_mesh.ray.intersects_any(ray_origins, ray_dirs)
        lit_counts += (~blocked).reshape(len(chunk), len(points_m)).sum(axis=0)
    return lit_counts * step_hours


# ---------------------------------------------------------------- outputs

def period_label(days: list[date]) -> str:
    first, last = days[0], days[-1]
    return f"{first:%m-%d}" if first == last else f"{first:%m-%d} to {last:%m-%d}"


def write_csv(path: Path, points_m: np.ndarray, hours: np.ndarray):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y", "z", "hours"])
        for (x, y, z), value in zip(points_m, hours):
            writer.writerow([f"{x:.4f}", f"{y:.4f}", f"{z:.4f}", f"{value:.4f}"])


def write_heatmap(path: Path, points_m, hours, spacing_m, title, context_mesh, max_hours):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    if context_mesh is not None and len(context_mesh.faces) <= FOOTPRINT_MAX_TRIANGLES:
        footprint = context_mesh.vertices[context_mesh.faces][:, :, :2]
        from matplotlib.collections import PolyCollection
        ax.add_collection(PolyCollection(footprint, facecolors="none", edgecolors="0.6",
                                         linewidths=0.15, alpha=0.5, zorder=2))
    xs, ys = points_m[:, 0], points_m[:, 1]
    marker_points = (spacing_m * 72 * fig.get_size_inches()[0]
                     / max(np.ptp(xs) + spacing_m, np.ptp(ys) + spacing_m, 1e-9)) ** 2
    scatter = ax.scatter(xs, ys, c=hours, s=marker_points * 0.8, marker="s", cmap="inferno",
                         vmin=0, vmax=max(max_hours, 1e-9), linewidths=0, zorder=1)
    fig.colorbar(scatter, ax=ax, shrink=0.8, label="direct sun hours")
    pad = spacing_m * 2
    ax.set_xlim(xs.min() - pad, xs.max() + pad)
    ax.set_ylim(ys.min() - pad, ys.max() + pad)
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)  [+Y = north unless --north set]")
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def print_sunpath_table(samples: list[SunSample], out_dir: Path | None):
    header = f"{'date':>5} {'time':>5} {'alt_deg':>8} {'azi_deg':>8}"
    print(header)
    rows = []
    for sample in samples:
        minutes = int(round(sample.hour * 60))
        clock = f"{minutes // 60:02d}:{minutes % 60:02d}"
        rows.append((f"{sample.day:%m-%d}", clock, sample.altitude, sample.azimuth))
        print(f"{rows[-1][0]:>5} {clock:>5} {sample.altitude:8.2f} {sample.azimuth:8.2f}")
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "sunpath.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "time", "altitude_deg", "azimuth_deg"])
            writer.writerows([(d, t, f"{a:.3f}", f"{z:.3f}") for d, t, a, z in rows])


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_argument_group("location (pick one)")
    location.add_argument("--site", choices=sorted(SITE_PRESETS))
    location.add_argument("--epw", help="EPW weather file; only its location is used")
    location.add_argument("--lat", type=float)
    location.add_argument("--lon", type=float)
    location.add_argument("--tz", type=float, help="UTC offset in hours, standard time (LA = -8)")
    location.add_argument("--north", type=float, default=0.0,
                          help="degrees north is rotated counter-clockwise from +Y (Ladybug)")
    period = parser.add_argument_group("period")
    period.add_argument("--date", help="single day MM-DD")
    period.add_argument("--start", help="first day MM-DD")
    period.add_argument("--end", help="last day MM-DD (inclusive)")
    period.add_argument("--hours", default="0-24", help="clock-hour window, e.g. 8-16")
    period.add_argument("--step-min", type=float, default=15.0, help="minutes; must divide the hours window exactly")
    parser.add_argument("--sunpath-only", action="store_true",
                        help="print sun altitude/azimuth table and exit")
    geometry = parser.add_argument_group("context geometry")
    geometry.add_argument("--geometry", type=Path, help=".3dm, .stl, .obj or .ply")
    geometry.add_argument("--layers", nargs="+", help=".3dm layer full-path substrings to keep")
    geometry.add_argument("--include-off-layers", action="store_true",
                          help="also use objects on layers saved as off (default: skip them)")
    geometry.add_argument("--units", help="mesh file units (mm, cm, m, in, ft); default meters")
    grid = parser.add_argument_group("analysis grid (model units)")
    grid.add_argument("--grid-rect", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"))
    grid.add_argument("--grid-z", type=float,
                      help="grid elevation (default 0 for rect; layer grids use their own z)")
    grid.add_argument("--grid-from-layer", help=".3dm layer with closed curves or surfaces")
    grid.add_argument("--spacing", type=float, help="grid spacing (model units)")
    grid.add_argument("--offset", type=float, default=0.01,
                      help="ray origin lift in meters to avoid self-hits (default 0.01)")
    parser.add_argument("--threshold", type=float, default=2.0,
                        help="report %% of points with at least this many hours")
    parser.add_argument("--out", type=Path, help="output directory")
    return parser


def resolve_days(args) -> list[date]:
    if args.date:
        return [parse_month_day(args.date)]
    if args.start and args.end:
        return date_range(parse_month_day(args.start), parse_month_day(args.end))
    raise SystemExit("Give --date MM-DD or both --start and --end")


def run(argv=None) -> dict | None:
    args = build_parser().parse_args(argv)
    site = resolve_site(args)
    days = resolve_days(args)
    hour_start, hour_end = parse_hours(args.hours)
    hours = timestep_hours(hour_start, hour_end, args.step_min)
    step_hours = args.step_min / 60.0

    if args.sunpath_only:
        print(f"# {site.name} lat {site.latitude} lon {site.longitude} UTC{site.time_zone:+g} "
              f"(standard time), {period_label(days)}, {args.hours}h, step {args.step_min:g} min, "
              "sun above horizon only; azimuth clockwise from north")
        print_sunpath_table(sun_samples(site, days, hours, args.north), args.out)
        return None

    if not args.out:
        raise SystemExit("--out DIR is required for an analysis run")
    if args.spacing is None or args.spacing <= 0:
        raise SystemExit("--spacing (model units, > 0) is required")
    if not (args.grid_rect or args.grid_from_layer):
        raise SystemExit("Give --grid-rect X0 Y0 X1 Y1 or --grid-from-layer NAME")

    warnings = []
    context_mesh, stats, model = None, GeometryStats(), None
    if args.geometry:
        context_mesh, stats, model = load_context(args.geometry, args.layers, args.units,
                                                  args.include_off_layers)
    else:
        warnings.append("No --geometry given: open-sky analysis")
        if args.units:
            stats.unit_system, stats.to_meters = args.units, unit_scale(args.units)
    to_meters = stats.to_meters

    if args.grid_from_layer:
        if model is None:
            raise SystemExit("--grid-from-layer needs a .3dm --geometry")
        points_m, notes = grid_from_layer(model, args.grid_from_layer, args.spacing,
                                          to_meters, args.grid_z)
        warnings.extend(sorted(set(notes)))
    else:
        grid_z = 0.0 if args.grid_z is None else args.grid_z
        points_m = rect_grid(*args.grid_rect, grid_z, args.spacing) * to_meters
    if len(points_m) == 0:
        raise SystemExit("Grid is empty; check --grid-rect and --spacing")

    samples = sun_samples(site, days, hours, args.north)
    sun_vectors = np.array([sample.vector for sample in samples]).reshape(-1, 3)
    sun_hours = direct_sun_hours(points_m, sun_vectors, step_hours, context_mesh, args.offset)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "sun_hours.csv", points_m, sun_hours)
    max_possible = len(samples) * step_hours / len(days)
    mean_per_day = sun_hours / len(days)
    title = (f"{site.name} ({site.latitude:.3f}, {site.longitude:.3f})  {period_label(days)}  "
             f"{args.hours}h  step {args.step_min:g} min\n"
             f"direct sun hours{' (total over ' + str(len(days)) + ' days)' if len(days) > 1 else ''}")
    write_heatmap(out_dir / "sun_hours.png", points_m, sun_hours, args.spacing * to_meters,
                  title, context_mesh, len(samples) * step_hours)

    summary = {
        "location": {"name": site.name, "latitude": site.latitude, "longitude": site.longitude,
                     "time_zone": site.time_zone, "source": site.source,
                     "north_angle_deg": args.north, "clock": "local standard time (no DST)"},
        "period": {"start": f"{days[0]:%m-%d}", "end": f"{days[-1]:%m-%d}", "days": len(days),
                   "hours": args.hours},
        "timestep_min": args.step_min,
        "daylight_timesteps": len(samples),
        "max_possible_hours_total": round(len(samples) * step_hours, 4),
        "max_possible_hours_per_day_mean": round(max_possible, 4),
        "grid": {"count": int(len(points_m)), "spacing_model_units": args.spacing,
                 "spacing_m": args.spacing * to_meters,
                 "source": f"layer:{args.grid_from_layer}" if args.grid_from_layer else "rect"},
        "hours_total": {"min": round(float(sun_hours.min()), 4),
                        "mean": round(float(sun_hours.mean()), 4),
                        "max": round(float(sun_hours.max()), 4)},
        "hours_per_day_mean": {"min": round(float(mean_per_day.min()), 4),
                               "mean": round(float(mean_per_day.mean()), 4),
                               "max": round(float(mean_per_day.max()), 4)},
        "threshold_hours": args.threshold,
        "threshold_basis": "total hours" if len(days) == 1 else "mean hours per day",
        "pct_points_at_or_above_threshold": round(
            float((mean_per_day >= args.threshold).mean() * 100), 2),
        "units": {"output": "meters", "model_unit_system": stats.unit_system,
                  "model_to_meters": to_meters},
        "geometry": {key: value for key, value in stats.__dict__.items() if key != "warnings"},
        "warnings": warnings + stats.warnings,
        "outputs": ["sun_hours.csv", "summary.json", "sun_hours.png"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({key: summary[key] for key in
                      ("grid", "hours_per_day_mean", "pct_points_at_or_above_threshold",
                       "warnings")}, indent=2))
    print(f"wrote {out_dir}/sun_hours.csv, summary.json, sun_hours.png")
    return summary


if __name__ == "__main__":
    run()
