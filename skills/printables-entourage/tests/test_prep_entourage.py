import csv
import sys
from pathlib import Path

import pytest
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prep_entourage


def prepare(root, name="figure", file="cube.stl"):
    spec = root / "spec.csv"
    with spec.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=["name", "file", "size_ft"])
        writer.writeheader()
        writer.writerow(dict(name=name, file=file, size_ft=1))
    return prep_entourage.main([str(spec), "--src", str(root / "src"), "--mmft", "6.35", "--out", str(root / "out")])


@pytest.fixture
def job(tmp_path):
    (tmp_path / "src").mkdir()
    trimesh.creation.box().export(tmp_path / "src/cube.stl")
    return tmp_path


def test_csv_name_cannot_escape_output(job):
    with pytest.raises(ValueError, match="name"):
        prepare(job, name="../escaped")
    assert not (job / "escaped.stl").exists()


def test_csv_file_cannot_escape_source(job):
    (job / "outside.stl").write_bytes((job / "src/cube.stl").read_bytes())
    with pytest.raises(ValueError, match="path"):
        prepare(job, file="../outside.stl")


def test_csv_output_does_not_replace_existing(job):
    (job / "out").mkdir()
    target = job / "out/figure.stl"
    target.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        prepare(job)
    assert target.read_bytes() == b"preserve"


def test_safe_csv_prepares_model(job):
    assert prepare(job) == 0
    assert trimesh.load(job / "out/figure.stl").is_watertight


def test_csv_rejects_symlink_and_absolute_paths(job):
    (job / "src/link.stl").symlink_to(job / "src/cube.stl")
    for value in ("link.stl", str(job / "src/cube.stl")):
        with pytest.raises(ValueError, match="path"):
            prepare(job, file=value)
    (job / "out").mkdir()
    (job / "out/figure.stl").symlink_to(job / "outside.stl")
    with pytest.raises(ValueError, match="symlink"):
        prepare(job)
