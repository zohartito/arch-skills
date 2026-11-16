#!/usr/bin/env python3
"""Stage fabrication files onto a mounted USB stick and prove every byte arrived.

Copies files (or the contents of folders) into a destination folder on a mounted volume,
fsyncs each file, re-reads each destination file and compares its SHA-256 with the source,
then writes MANIFEST-SHA256.txt (shasum -c format) next to them.

Exit codes: 0 all verified, 1 at least one mismatch, 2 refused (volume not mounted, bad input,
or an existing different file without --overwrite).

    python3 stage_usb.py FILE_OR_DIR [...] --dest "/Volumes/USB/LASER - Mon Oct 5"
    python3 stage_usb.py ... --dest /tmp/x --allow-local      # tests only: skip the mount check

Skipped automatically: dotfiles (.DS_Store) and anything under a folder whose name starts
with "_superseded", so old versions never reach the lab computer.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import sys
import tempfile
from pathlib import Path

MANIFEST_NAME = "MANIFEST-SHA256.txt"
CHUNK = 1024 * 1024
SYSTEM_MOUNTS = {Path("/"), Path("/System/Volumes/Data")}


def sha256_of(path: Path, bypass_cache: bool = False) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        nocache = getattr(fcntl, "F_NOCACHE", None)   # macOS: read from the device, not the page cache
        if bypass_cache and nocache is not None:
            try:
                fcntl.fcntl(handle.fileno(), nocache, 1)
            except OSError:
                pass
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def mount_point_of(path: Path) -> Path:
    """Nearest existing ancestor of path that is a mount point."""
    current = path.resolve()
    while not current.exists():
        current = current.parent
    while not os.path.ismount(current):
        current = current.parent
    return current


def is_skipped(relative: Path) -> bool:
    return any(part.startswith(".") or part.startswith("_superseded") for part in relative.parts)


def collect(sources: list[Path]) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """(source file, path relative to dest) pairs, plus the skipped source files."""
    pairs, skipped = [], []
    for source in sources:
        if is_skipped(source.absolute()):
            skipped.append(source)
            continue
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(source)
                if is_skipped(relative):
                    skipped.append(path)
                else:
                    pairs.append((path, relative))
        elif source.is_file():
            if is_skipped(Path(source.name)):
                skipped.append(source)
            else:
                pairs.append((source, Path(source.name)))
        else:
            raise FileNotFoundError(source)
    return pairs, skipped


def fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_synced(source: Path, target: Path) -> None:
    if target.exists() and source.samefile(target):
        raise ValueError("source and destination are the same file")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with source.open("rb") as reader, tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as writer:
            temporary = Path(writer.name)
            while block := reader.read(CHUNK):
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        os.utime(temporary, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns))
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    fsync_dir(target.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", type=Path, help="files, or folders whose contents are copied")
    parser.add_argument("--dest", required=True, type=Path, help="destination folder on the mounted volume")
    parser.add_argument("--overwrite", action="store_true", help="replace existing files whose content differs")
    parser.add_argument("--allow-local", action="store_true", help="tests only: allow a destination on the system disk")
    args = parser.parse_args()

    dest = args.dest.expanduser()
    mount = mount_point_of(dest)
    if mount in SYSTEM_MOUNTS and not args.allow_local:
        print(f"REFUSED: {dest} is not on a mounted removable volume (nearest mount: {mount}). "
              f"Plug in the USB and pass its /Volumes/<NAME>/... path.", file=sys.stderr)
        return 2

    try:
        pairs, skipped = collect([s.expanduser() for s in args.sources])
    except FileNotFoundError as missing:
        print(f"REFUSED: source not found: {missing}", file=sys.stderr)
        return 2
    if not pairs:
        print("REFUSED: nothing to copy", file=sys.stderr)
        return 2
    names = [relative for _, relative in pairs]
    duplicates = {str(n) for n in names if names.count(n) > 1}
    if duplicates:
        print(f"REFUSED: two sources map to the same name: {sorted(duplicates)}", file=sys.stderr)
        return 2

    if any((dest / r).exists() and path.samefile(dest / r) for path, r in pairs):
        print("REFUSED: source and destination are the same file", file=sys.stderr)
        return 2
    source_hashes = {relative: sha256_of(path) for path, relative in pairs}
    conflicts = [r for _, r in pairs if (dest / r).exists() and sha256_of(dest / r) != source_hashes[r]]
    if conflicts and not args.overwrite:
        print("REFUSED: these exist on the volume with different content (rename the new version, "
              "or pass --overwrite):", file=sys.stderr)
        for relative in conflicts:
            print(f"  {relative}", file=sys.stderr)
        return 2

    for path in skipped:
        print(f"skipped  {path}")
    dest.mkdir(parents=True, exist_ok=True)
    for path, relative in pairs:
        copy_synced(path, dest / relative)
    os.sync()

    failures = 0
    lines = []
    for path, relative in pairs:
        expected = source_hashes[relative]
        actual = sha256_of(dest / relative, bypass_cache=True)
        size_kb = (dest / relative).stat().st_size / 1024
        status = "OK " if actual == expected else "BAD"
        failures += actual != expected
        print(f"{status} {expected[:12]}  {size_kb:9.1f} KB  {relative}")
        lines.append(f"{expected}  {relative.as_posix()}")

    # files already in the folder from an earlier run stay listed, so the manifest always covers the whole folder
    manifest = dest / MANIFEST_NAME
    staged = set(names)
    for path in sorted(dest.rglob("*")):
        relative = path.relative_to(dest)
        if path.is_file() and path != manifest and relative not in staged and not is_skipped(relative):
            print(f"kept {relative} (already on the volume, not staged this run)")
            lines.append(f"{sha256_of(path, bypass_cache=True)}  {relative.as_posix()}")

    with manifest.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    fsync_dir(dest)
    os.sync()

    print(f"{len(pairs) - failures}/{len(pairs)} verified; manifest {manifest}")
    if failures:
        print(f"FAILED: {failures} file(s) differ from the source. Do not take this USB to the lab.", file=sys.stderr)
        return 1
    if mount not in SYSTEM_MOUNTS:
        print(f"Eject before unplugging: diskutil eject \"{mount}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
