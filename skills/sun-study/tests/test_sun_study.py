"""Analytic checks for sun_study.py. Run: python -m pytest tests"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
import rhino3dm
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sun_study  # noqa: E402

VENICE = sun_study.Site("venice-ca", 33.985, -118.469, -8.0, "preset")
OBLIQUITY = 23.44


def solar_noon_altitude(month, day):
    from ladybug.sunpath import Sunpath
    sunpath = Sunpath(VENICE.latitude, VENICE.longitude, VENICE.time_zone)
    return sunpath.calculate_sun(month, day, 12, is_solar_time=True).altitude


def test_winter_solstice_noon_altitude():
    expected = 90 - VENICE.latitude - OBLIQUITY  # ~32.58
    assert solar_noon_altitude(12, 21) == pytest.approx(expected, abs=0.5)


def test_summer_solstice_noon_altitude():
    expected = 90 - VENICE.latitude + OBLIQUITY  # ~79.46
    assert solar_noon_altitude(6, 21) == pytest.approx(expected, abs=0.5)


def test_sun_vector_points_at_sun():
    sample = sun_study.sun_samples(VENICE, [sun_study.parse_month_day("12-21")], [12.0])[0]
    altitude_from_vector = math.degrees(math.asin(sample.vector[2]))
    assert altitude_from_vector == pytest.approx(sample.altitude, abs=1e-6)
    assert sample.vector[1] < 0  # winter noon sun is due south (-Y)


def east_west_wall(height, length=200.0, thickness=0.2):
    """Wall along X, centred on y=0, standing on z=0."""
    wall = trimesh.creation.box(extents=(length, thickness, height))
    wall.apply_translation((0, 0, height / 2))
    return wall


def test_wall_shadow_length_matches_trigonometry():
    height, thickness = 5.0, 0.2
    wall = east_west_wall(height, thickness=thickness)
    sample = sun_study.sun_samples(VENICE, [sun_study.parse_month_day("12-21")], [12.0])[0]
    to_sun = np.array([sample.vector])
    horizontal = to_sun[0, :2] / np.linalg.norm(to_sun[0, :2])
    shadow_length = height / math.tan(math.radians(sample.altitude))  # along azimuth
    # Walk away from the wall's north face along the anti-sun direction (shadow direction).
    shadow_dir = -horizontal
    north_face = np.array([0.0, thickness / 2])
    shaded = [0.2, 0.5, 0.9, 0.98]
    lit = [1.02, 1.1, 1.5, 3.0]
    for fraction, expect_lit in [(f, False) for f in shaded] + [(f, True) for f in lit]:
        # Distance along shadow direction, measured from the north face's top edge footprint.
        distance = fraction * shadow_length
        point = np.array([[*(north_face + shadow_dir * distance), 0.0]])
        hours = sun_study.direct_sun_hours(point, to_sun, 1.0, wall)
        assert (hours[0] == 1.0) == expect_lit, (fraction, distance, shadow_length)


def test_open_ground_gets_all_daylight_steps():
    days = [sun_study.parse_month_day("03-20")]
    step_min = 15
    hours = sun_study.timestep_hours(0, 24, step_min)
    samples = sun_study.sun_samples(VENICE, days, hours)
    vectors = np.array([s.vector for s in samples])
    points = sun_study.rect_grid(0, 0, 10, 10, 0, 2)
    # Far-away obstacle that never intersects upward rays from the grid.
    far_box = trimesh.creation.box(extents=(1, 1, 1))
    far_box.apply_translation((0, 0, -100))
    result = sun_study.direct_sun_hours(points, vectors, step_min / 60, far_box)
    expected = len(samples) * step_min / 60
    assert 11.5 < expected < 12.6  # equinox day length sanity
    assert np.allclose(result, expected)
    assert np.allclose(sun_study.direct_sun_hours(points, vectors, step_min / 60, None), expected)


def write_mm_box_3dm(path: Path, size_mm=1000.0):
    model = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Millimeters
    layer = rhino3dm.Layer()
    layer.Name = "Context"
    model.Layers.Add(layer)
    box = trimesh.creation.box(extents=(size_mm, size_mm, size_mm))
    box.apply_translation((0, 0, size_mm / 2))
    mesh = rhino3dm.Mesh()
    for x, y, z in box.vertices:
        mesh.Vertices.Add(float(x), float(y), float(z))
    for a, b, c in box.faces:
        mesh.Faces.AddFace(int(a), int(b), int(c))
    attributes = rhino3dm.ObjectAttributes()
    attributes.LayerIndex = 0
    model.Objects.AddMesh(mesh, attributes)
    model.Objects.AddLine(rhino3dm.Point3d(0, 0, 0), rhino3dm.Point3d(1, 0, 0))  # ignored
    assert model.Write(str(path), 8)


def test_3dm_millimeters_convert_to_meters(tmp_path):
    path = tmp_path / "box_mm.3dm"
    write_mm_box_3dm(path)
    mesh, stats, _ = sun_study.load_context(path, None, None)
    assert stats.unit_system == "Millimeters"
    assert stats.to_meters == pytest.approx(0.001)
    assert stats.objects_meshed == 1 and stats.objects_no_mesh == 0
    assert np.allclose(mesh.bounds, [[-0.5, -0.5, 0.0], [0.5, 0.5, 1.0]])
    filtered, filtered_stats, _ = sun_study.load_context(path, ["NoSuchLayer"], None)
    assert filtered is None and filtered_stats.objects_considered == 0


def test_cli_end_to_end(tmp_path):
    path = tmp_path / "box_mm.3dm"
    write_mm_box_3dm(path)
    out = tmp_path / "out"
    summary = sun_study.run([
        "--site", "venice-ca", "--date", "12-21", "--hours", "8-16", "--step-min", "30",
        "--geometry", str(path), "--grid-rect", "-3000", "-3000", "3000", "3000",
        "--spacing", "500", "--out", str(out)])
    assert {p.name for p in out.iterdir()} == {"sun_hours.csv", "summary.json", "sun_hours.png"}
    saved = json.loads((out / "summary.json").read_text())
    assert saved["grid"]["count"] == 144
    assert saved["grid"]["spacing_m"] == pytest.approx(0.5)
    assert saved["hours_total"]["max"] == pytest.approx(8.0)  # unobstructed 8-16 window
    assert saved["hours_total"]["min"] < 8.0  # box shades its north side
    assert summary["units"]["model_to_meters"] == pytest.approx(0.001)


def test_off_layer_objects_skipped_unless_requested(tmp_path):
    path = tmp_path / "off_layer.3dm"
    write_mm_box_3dm(path)
    model = rhino3dm.File3dm.Read(str(path))
    model.Layers[0].Visible = False
    model.Write(str(path), 8)
    mesh, stats, _ = sun_study.load_context(path, None, None)
    assert mesh is None and stats.objects_off_layer_skipped == 1
    mesh, stats, _ = sun_study.load_context(path, None, None, include_off_layers=True)
    assert mesh is not None and stats.objects_meshed == 1


def test_grid_from_layer_closed_curve(tmp_path):
    path = tmp_path / "grid_layer.3dm"
    write_mm_box_3dm(path)
    model = rhino3dm.File3dm.Read(str(path))
    grid_layer = rhino3dm.Layer()
    grid_layer.Name = "Court"
    index = model.Layers.Add(grid_layer)
    corners = [(-4000, -4000, 0), (4000, -4000, 0), (4000, -2000, 0), (-4000, -2000, 0),
               (-4000, -4000, 0)]
    curve = rhino3dm.PolylineCurve([rhino3dm.Point3d(*corner) for corner in corners])
    attributes = rhino3dm.ObjectAttributes()
    attributes.LayerIndex = index
    model.Objects.AddCurve(curve, attributes)
    model.Write(str(path), 8)
    summary = sun_study.run([
        "--site", "venice-ca", "--date", "12-21", "--hours", "8-16", "--step-min", "60",
        "--geometry", str(path), "--grid-from-layer", "Court", "--spacing", "1000",
        "--out", str(tmp_path / "out")])
    assert summary["grid"]["count"] == 16  # 8 m x 2 m strip at 1 m spacing
    # The strip lies south of the box, so nothing shades it.
    assert summary["hours_total"]["min"] == pytest.approx(8.0)


def test_stl_with_units(tmp_path):
    wall = east_west_wall(5.0)
    wall.apply_scale(1000.0)  # same wall in millimetres
    path = tmp_path / "wall_mm.stl"
    wall.export(path)
    mesh, stats, _ = sun_study.load_context(path, None, "mm")
    assert stats.to_meters == pytest.approx(0.001)
    assert mesh.bounds[1, 2] == pytest.approx(5.0)
