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
