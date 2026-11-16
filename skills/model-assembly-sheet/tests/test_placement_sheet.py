import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import placement_sheet


def sheet_job(root, out="sheet.pdf"):
    (root / "posts.csv").write_text("post,x,y,above\np1,0,0,10\n")
    spec = {"posts": {"csv": "posts.csv", "name": "post", "x": "x", "y": "y", "above": "above"}, "out": out}
    source = root / "sheet.json"
    source.write_text(json.dumps(spec))
    return source


def test_sheet_output_cannot_escape_spec_root(tmp_path):
    root = tmp_path / "job"
    root.mkdir()
    source = sheet_job(root, "../escaped.pdf")
    with pytest.raises(ValueError, match="path"):
        placement_sheet.main(str(source))
    assert not (tmp_path / "escaped.pdf").exists()


@pytest.mark.parametrize("suffix", [".pdf", ".png", "_post-cut-list.csv"])
def test_sheet_does_not_replace_any_output(tmp_path, suffix):
    source = sheet_job(tmp_path)
    sentinel = tmp_path / ("sheet" + suffix)
    sentinel.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        placement_sheet.main(str(source))
    assert sentinel.read_bytes() == b"preserve"


def test_safe_sheet_writes_all_outputs(tmp_path):
    assert placement_sheet.main(str(sheet_job(tmp_path))) == 0
    assert (tmp_path / "sheet.pdf").read_bytes().startswith(b"%PDF")
    assert (tmp_path / "sheet.png").read_bytes().startswith(b"\x89PNG")
    assert "p1" in (tmp_path / "sheet_post-cut-list.csv").read_text()


@pytest.mark.parametrize("field", ["placements", "stl", "posts"])
def test_sheet_input_paths_are_contained(tmp_path, field):
    source = sheet_job(tmp_path)
    spec = json.loads(source.read_text())
    if field == "stl":
        spec["parts"] = [{"stl": "../outside.stl"}]
    elif field == "posts":
        spec["posts"]["csv"] = "../outside.csv"
    else:
        spec["placements"] = "../outside.json"
    source.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="path"):
        placement_sheet.main(str(source))


def test_sheet_rejects_symlink_and_absolute_paths(tmp_path):
    (tmp_path / "link").symlink_to(tmp_path / "outside")
    for value in ("link", str(tmp_path / "absolute.pdf")):
        with pytest.raises(ValueError, match="path"):
            placement_sheet.checked_path(tmp_path, value)
