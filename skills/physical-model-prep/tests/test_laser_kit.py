import sys
from pathlib import Path

import rhino3dm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import laser_kit as laser


def test_square_holes_preserves_unrelated_cut_geometry(tmp_path, capsys):
    model = laser.new_file()
    cut = laser.layer_index(model, "CUT")
    laser.add(model, rhino3dm.Circle(1.5 * laser.MM).ToNurbsCurve(), cut, "round hole")
    laser.add(model, laser.polyline([(0, 0), (0.1, 0)]), cut, "short line")
    corners = [(0, 0), (4 * laser.MM, 0), (4 * laser.MM, 3 * laser.MM), (0, 3 * laser.MM), (0, 0)]
    for n, (a, b) in enumerate(zip(corners, corners[1:])):
        laser.add(model, laser.polyline([a, b]), cut, f"notch {n}")
    laser.add(model, laser.polyline(corners), cut, "closed rectangle")
    laser.add(model, laser.square(0, 0, 10 * laser.MM), cut, "outline")
    before = {o.Attributes.Name: o.Geometry.Encode() for o in model.Objects if o.Attributes.Name != "round hole"}
    source, out = tmp_path / "in.3dm", tmp_path / "out.3dm"
    assert model.Write(str(source), 7)
    assert laser.main(["square-holes", str(source), "--out", str(out)]) == 0
    saved = rhino3dm.File3dm.Read(str(out))
    after = {o.Attributes.Name: o.Geometry.Encode() for o in saved.Objects}
    assert before.items() <= after.items()
    assert len(saved.Objects) == len(model.Objects)
    assert "1 holes replaced" in capsys.readouterr().out
