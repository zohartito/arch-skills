"""Check the hash lock against installed distribution dependency metadata."""
import importlib.metadata
from pathlib import Path
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

LOCK = Path(__file__).resolve().parents[1] / "requirements-arch-tools.txt"


def locked_requirements():
    return [line for line in LOCK.read_text().replace("\\\n", " ").splitlines()
            if line.strip() and not line.startswith(("#", "--"))]


def test_artifact_hashes_are_required():
    assert "--require-hashes" in LOCK.read_text().splitlines()
    for line in locked_requirements():
        assert re.fullmatch(r"[\w.-]+==[^\s]+(?:\s+--hash=sha256:[0-9a-f]{64})+\s*", line), line


def test_lock_covers_active_transitive_dependencies():
    pins = {canonicalize_name(req.name): req for line in locked_requirements()
            for req in [Requirement(line.split(" --hash")[0].strip())]}
    for name, pin in pins.items():
        distribution = importlib.metadata.distribution(name)
        assert distribution.version in pin.specifier
        for raw in distribution.requires or []:
            dependency = Requirement(raw)
            if dependency.marker and not dependency.marker.evaluate({"extra": ""}):
                continue
            dep_name = canonicalize_name(dependency.name)
            assert dep_name in pins, f"{name} leaves {dep_name} unlocked"
            version = next(iter(pins[dep_name].specifier)).version
            assert version in dependency.specifier
