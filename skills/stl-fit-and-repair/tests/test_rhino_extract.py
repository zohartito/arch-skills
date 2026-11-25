import sys
from pathlib import Path

import pytest
import rhino3dm
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rhino_extract


def test_saved_extrusion_without_render_mesh(tmp_path, capsys):
    model = rhino3dm.File3dm()
    layer = rhino3dm.Layer()
    layer.Name = "parts"
    model.Layers.Add(layer)
    profile = rhino3dm.PolylineCurve([rhino3dm.Point3d(*p) for p in
                                    [(0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0), (0, 0, 0)]])
    extrusion = rhino3dm.Extrusion.Create(profile, 4, True)
    assert extrusion.GetMesh(rhino3dm.MeshType.Render) is None
    model.Objects.AddExtrusion(extrusion, rhino3dm.ObjectAttributes())
    source, out = tmp_path / "box.3dm", tmp_path / "box.stl"
    assert model.Write(str(source), 8)
    assert rhino_extract.main([str(source), "--mmft", "1", "--out", str(out)]) == 0
    mesh = trimesh.load(out)
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(24)
    assert "hull fallback" in capsys.readouterr().out
