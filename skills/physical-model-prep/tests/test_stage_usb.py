"""Offline staging regressions; all sources and destinations are temporary."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_usb


def stage(monkeypatch, sources, dest, *extra):
    monkeypatch.setattr(sys, "argv", ["stage_usb", *map(str, sources), "--dest", str(dest),
                                    "--allow-local", *extra])
    monkeypatch.setattr(stage_usb.os, "sync", lambda: None)
    return stage_usb.main()


@pytest.mark.parametrize("selection", ["file", "folder", "hardlink"])
def test_same_source_destination_preserves_bytes(tmp_path, monkeypatch, selection):
    dest = tmp_path / "usb"
    dest.mkdir()
    source = dest / "part.dxf"
    source.write_bytes(b"only copy of fabrication data")
    selected = dest if selection == "folder" else source
    if selection == "hardlink":
        selected = tmp_path / "part.dxf"
        selected.hardlink_to(source)
    assert stage(monkeypatch, [selected], dest) == 2
    assert source.read_bytes() == b"only copy of fabrication data"


def test_copy_failure_preserves_existing_destination(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new bytes")
    target.write_bytes(b"old bytes")
    def fail_sync(fd):
        raise OSError("simulated failed flush")
    monkeypatch.setattr(stage_usb.os, "fsync", fail_sync)
    with pytest.raises(OSError, match="failed flush"):
        stage_usb.copy_synced(source, target)
    assert target.read_bytes() == b"old bytes"
    assert source.read_bytes() == b"new bytes"


@pytest.mark.parametrize("selection", ["file", "folder", "glob", "ancestor"])
def test_superseded_sources_are_skipped(tmp_path, monkeypatch, selection):
    project = tmp_path / "project"
    old = project / "_superseded-v1" / "nested" / "old.dxf"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old version")
    current = project / "current.dxf"
    current.write_bytes(b"current version")
    sources = {"file": [old], "folder": [old.parent.parent],
               "glob": sorted(project.glob("*")), "ancestor": [old.parent]}[selection]
    dest = tmp_path / "usb"
    assert stage(monkeypatch, sources, dest) == (0 if selection == "glob" else 2)
    assert not list(dest.rglob("old.dxf"))
    assert old.read_bytes() == b"old version"
    if selection == "glob":
        assert (dest / "current.dxf").read_bytes() == b"current version"
