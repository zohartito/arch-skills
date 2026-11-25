import sys
from pathlib import Path

import pytest
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fit_to_mates
import meshkit as mk


@pytest.mark.parametrize("thickness,obstacle_z,obstacle_height,collision_z", [
    (0.4, 2.2, 0.1, 2), (2, 5.1, 2.8, 5)])
def test_thin_overhang_between_old_samples_fails(tmp_path, thickness, obstacle_z, obstacle_height, collision_z):
    part = trimesh.creation.box(extents=(20, 20, thickness))
    part.apply_translation((0, 0, thickness / 2))
    mate = trimesh.creation.box(extents=(10, 20, obstacle_height))
    mate.apply_translation((0, 0, obstacle_z + obstacle_height / 2))
    source, mates, out = [tmp_path / name for name in ("part.stl", "mates.stl", "fit.stl")]
    part.export(source)
    mate.export(mates)
    code = fit_to_mates.main([str(source), "--mates", str(mates), "--out", str(out)])
    final = mk.to_manifold(trimesh.load(out))
    assert (final.translate((0, 0, collision_z)) ^ mk.to_manifold(mate)).volume() > 19
    assert code == 1


def test_unobstructed_drop_passes(tmp_path):
    source, mates, out = [tmp_path / name for name in ("part.stl", "mates.stl", "fit.stl")]
    trimesh.creation.box(extents=(20, 20, 2)).export(source)
    mate = trimesh.creation.box(extents=(10, 20, 2))
    mate.apply_translation((30, 0, 0))
    mate.export(mates)
    assert fit_to_mates.main([str(source), "--mates", str(mates), "--out", str(out)]) == 0


def test_sweep_preserves_through_hole():
    import manifold3d as mf
    ring = mf.Manifold.cube((20, 20, 2), True) - mf.Manifold.cube((10, 10, 4), True)
    post = mf.Manifold.cube((8, 8, 40), True)
    swept = fit_to_mates.swept_volume(ring)
    assert swept.volume() == pytest.approx(300 * 32)
    assert (swept ^ post).volume() == pytest.approx(0)
