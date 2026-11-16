import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import printables


def fetch(monkeypatch, out, name):
    monkeypatch.setattr(printables, "model", lambda _: {"stls": [{"name": name, "id": "1"}]})
    monkeypatch.setattr(printables, "download_link", lambda *_: "unused")
    monkeypatch.setattr(printables, "fetch_bytes", lambda _: b"downloaded mesh")
    printables.cmd_fetch(SimpleNamespace(model_id="1", out=out, match="", every=1, max=12, ledger=None))


@pytest.mark.parametrize("name", ["../escape.stl", "nested/escape.stl", "nested\\escape.stl", "/escape.stl"])
def test_download_rejects_unsafe_filename(tmp_path, monkeypatch, name):
    # Absolute-path probe stays in scratch even on the vulnerable implementation.
    if name.startswith("/"):
        name = str(tmp_path / "absolute.stl")
    with pytest.raises(ValueError, match="filename"):
        fetch(monkeypatch, tmp_path / "out", name)
    assert not (tmp_path / "escape.stl").exists()
    assert not (tmp_path / "absolute.stl").exists()


def test_download_rejects_symlink(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"preserve")
    (out / "model.stl").symlink_to(sentinel)
    with pytest.raises(ValueError, match="symlink"):
        fetch(monkeypatch, out, "model.stl")
    assert sentinel.read_bytes() == b"preserve"


def test_safe_download_and_existing_file_preserved(tmp_path, monkeypatch):
    out = tmp_path / "out"
    fetch(monkeypatch, out, "model.stl")
    assert (out / "model.stl").read_bytes() == b"downloaded mesh"
    (out / "model.stl").write_bytes(b"existing")
    fetch(monkeypatch, out, "model.stl")
    assert (out / "model.stl").read_bytes() == b"existing"


def test_download_exclusive_creation_after_fetch(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(printables, "model", lambda _: {"stls": [{"name": "model.stl", "id": "1"}]})
    monkeypatch.setattr(printables, "download_link", lambda *_: "unused")
    def race(_):
        (out / "model.stl").write_bytes(b"created during fetch")
        return b"downloaded mesh"
    monkeypatch.setattr(printables, "fetch_bytes", race)
    with pytest.raises(FileExistsError):
        printables.cmd_fetch(SimpleNamespace(model_id="1", out=out, match="", every=1, max=12, ledger=None))
    assert (out / "model.stl").read_bytes() == b"created during fetch"
