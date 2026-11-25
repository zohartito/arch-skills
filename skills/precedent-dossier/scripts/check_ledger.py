#!/usr/bin/env python3
"""Validate a precedent dossier: SOURCES.csv integrity and citations in its notes.

Hard errors (exit 1): missing required columns, malformed or duplicate source ids,
non-http(s) URLs, empty label/date/class, notes citing ids absent from the ledger, and
ASSET-INVENTORY.json problems (missing/malformed inventory when assets/ or evidence/ hold
files, unlisted/missing files, bad records, unknown source ids, URL mismatches, wrong
bytes/sha256, duplicate, absolute, escaping or symlinked paths).
Warnings (exit 0): ledger rows never cited, inline URLs not in the ledger, number+unit
lines with missing/incomplete provenance, boilerplate qualifications, duplicate URLs.
With --strict-dimensions, dimension warnings become hard errors (exit 1).

Markdown links whose URL is a ledger row count as citations of that row, so dossiers
that cite by inline URL (e.g. older dossiers) can be checked too.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

REQUIRED_COLUMNS = [
    "source_id", "url", "label", "access_date_local",
    "source_class", "qualification", "evidence_route",
]
NON_EMPTY_COLUMNS = ["label", "access_date_local", "source_class"]
KNOWN_CLASSES = {
    "architect project source",
    "architect firm source",
    "official civic / planning record",
    "project builder source",
    "publication / corroboration",
    "listing / property corroboration",
    "developer / marketing",
    "book / academic",
    "social / user-posted",
}

SOURCE_ID = re.compile(r"\bS\d{3,}\b")
ID_RANGE = re.compile(r"\bS\d{3,}\s*(?:–|—|-|to)\s*S\d{3,}\b")  # id-block declarations
URL = re.compile(r"https?://[^\s<>()\[\]\"'`|]+")
DIMENSION = re.compile(
    r"\d(?:[\d,.]*\d)?\s*-?\s*"
    r"(?:sq\.?\s*ft|[Ss]quare[- ]f(?:oot|eet)|SF|sf|ft²|ft2|ft|feet|foot|"
    r"mm|cm|m²|m2|m|'|\"|′|″)"
    r"(?![A-Za-z0-9²])"
)
# These are structural checks, not verification of a source or its measurements.
PINPOINT = re.compile(
    r"\b(?:(?:pp?\.?|pages?|fig(?:ure)?s?\.?)\s*\d+[A-Za-z]?\b|"
    r"sheet\s+(?:[A-Za-z]+[-.]?)?\d+[A-Za-z0-9.-]*\b|"
    r"(?:timestamp|time|t)\s*[:=]?\s*\d{1,2}:\d{2}(?::\d{2})?\b)", re.I
)
PAGE_FRAGMENT = re.compile(r"#page=[1-9]\d*(?:\b|$)", re.I)
WRITTEN = re.compile(r"\bwritten\b", re.I)
SCALED = re.compile(r"\bscaled\b", re.I)
PUBLISHED = re.compile(r"\bpublished[- ]figures?\b", re.I)
DERIVED = re.compile(r"\bderived\b", re.I)
DERIVED_METHOD = re.compile(r"\bderived\s*:\s*([^\[\]\n|]*)", re.I)
POSITIVE = r"(?:[1-9]\d*(?:\.\d+)?|0?\.\d*[1-9]\d*)"
SCALE_LENGTH = (
    rf"{POSITIVE}(?:\s*/\s*{POSITIVE})?\s*"
    r"(?:mm|cm|m\b|ft\b|in\b|[\"'′″])(?:\s*-\s*\d+\s*[\"″])?"
)
SCALE = re.compile(
    rf"\b(?:scaled(?:\s+at)?|scale)\s*[:=(,]?\s*"
    rf"(?:{POSITIVE}\s*:\s*{POSITIVE}(?![\w.:])|"
    rf"{SCALE_LENGTH}\s*=\s*{SCALE_LENGTH})(?![\w.])", re.I
)
UNSOURCED_TAG = "[unsourced]"
INVENTORY = "ASSET-INVENTORY.json"
ASSET_DIRS = ("assets", "evidence")
BOILERPLATE_SHARE = 0.5   # warn when one qualification text covers more than half the rows
BOILERPLATE_MIN_ROWS = 10


def normalize_url(url: str) -> str:
    """Compare URLs without fragment, trailing slash or trailing punctuation."""
    url = url.rstrip(".,;:!?*_")
    url = url.split("#", 1)[0]
    return url.rstrip("/")


def clip(text: str, width: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


class Report:
    def __init__(self):
        self.errors = defaultdict(list)
        self.warnings = defaultdict(list)

    def error(self, kind, message):
        self.errors[kind].append(message)

    def warn(self, kind, message):
        self.warnings[kind].append(message)


def check_ledger(ledger_path: Path, report: Report):
    """Return {source_id: row} and {normalized_url: source_id} for valid rows."""
    ids, url_to_id = {}, {}
    if not ledger_path.is_file():
        report.error("ledger", f"{ledger_path.name} not found")
        return ids, url_to_id

    with ledger_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = [c.strip() for c in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in columns]
        extra = [c for c in columns if c not in REQUIRED_COLUMNS]
        if missing:
            report.error("columns", f"missing required column(s): {', '.join(missing)}")
        if extra:
            report.warn("columns", f"extra column(s) not in the standard ledger: {', '.join(extra)}")
        rows = list(reader)

    seen_urls = {}
    qualifications = Counter()
    today = date.today()
    for line_no, raw in enumerate(rows, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        sid = row.get("source_id", "")
        where = f"SOURCES.csv:{line_no}"
        if not re.fullmatch(r"S\d{3,}", sid):
            report.error("ledger-id", f"{where} malformed source_id {sid!r} (expected S###)")
        elif sid in ids:
            report.error("ledger-id", f"{where} duplicate source_id {sid}")
        else:
            ids[sid] = row

        url = row.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in url:
            report.error("ledger-url", f"{where} {sid}: malformed URL {url!r}")
        else:
            key = normalize_url(url)
            if key in seen_urls:
                report.warn("duplicate-url", f"{where} {sid} repeats the URL of {seen_urls[key]}; keep one row")
            else:
                seen_urls[key] = sid
                if re.fullmatch(r"S\d{3,}", sid):
                    url_to_id[key] = sid

        for column in NON_EMPTY_COLUMNS:
            if column in columns and not row.get(column):
                report.error("ledger-empty", f"{where} {sid}: empty {column}")

        access = row.get("access_date_local", "")
        if access:
            try:
                if date.fromisoformat(access) > today:
                    report.warn("ledger-date", f"{where} {sid}: access date {access} is in the future")
            except ValueError:
                report.warn("ledger-date", f"{where} {sid}: access date {access!r} is not YYYY-MM-DD")

        source_class = row.get("source_class", "")
        if source_class and source_class not in KNOWN_CLASSES:
            report.warn("source-class", f"{where} {sid}: unknown source_class {source_class!r}")

        qualification = row.get("qualification", "")
        if "qualification" in columns and not qualification:
            report.warn("qualification", f"{where} {sid}: empty qualification")
        if qualification:
            qualifications[qualification] += 1

    if len(rows) >= BOILERPLATE_MIN_ROWS:
        for text, count in qualifications.most_common():
            if count / len(rows) > BOILERPLATE_SHARE:
                report.warn(
                    "qualification",
                    f"{count}/{len(rows)} rows share one qualification ({clip(text, 60)!r}); "
                    "qualifications should be specific to each source",
                )
    return ids, url_to_id


def dimension_provenance(text, has_source, fragment_pinpoint=False):
    """Return missing evidence for one Markdown claim/row, with URL text removed.

    Inspect the entire row so source and method may occupy separate table cells.
    Published figures are reported values, not measured dimensions. Derived values
    need an explicit method and ledgered inputs, not their own drawing scale.
    """
    missing = []
    if not has_source:
        missing.append("ledgered source/input (S### or ledger URL)")
    if DERIVED.search(text):
        method = DERIVED_METHOD.search(text)
        method = SOURCE_ID.sub("", method[1]).strip(" `*_:;,.()-") if method else ""
        if not any(char.isalnum() for char in method) or method.lower() in {"tbd", "todo", "unknown", "n/a"}:
            missing.append("nonempty [derived: method]")
    elif not PUBLISHED.search(text):
        if not (PINPOINT.search(text) or fragment_pinpoint):
            missing.append("source pinpoint (page, sheet, figure or timestamp)")
        if not (WRITTEN.search(text) or SCALED.search(text)):
            missing.append("written/scaled marker (or label as a published figure / derived value)")
        if SCALED.search(text) and not SCALE.search(text):
            missing.append("explicit scale (e.g. scaled 1:100 or scaled 1/8\"=1'-0\")")
    return missing


def scan_references(dossier: Path, ledger_ids, url_to_id, report: Report, strict_dimensions=False):
    """Scan .md (citations + dimensions) and .json (citations only). Return stats."""
    cited = Counter()
    stats = Counter()
    unledgered = []
    files = sorted(p for p in dossier.rglob("*") if p.is_file() and p.suffix in (".md", ".json"))
    for path in files:
        rel = path.relative_to(dossier)
        is_markdown = path.suffix == ".md"
        stats["md_files" if is_markdown else "json_files"] += 1
        in_fence = False
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if is_markdown and line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            where = f"{rel}:{line_no}"
            text = ID_RANGE.sub(" ", line)

            line_ids = set(SOURCE_ID.findall(text))
            for sid in line_ids:
                stats["id_refs"] += 1
                if sid in ledger_ids:
                    cited[sid] += 1
                else:
                    report.error("missing-id", f"{where} cites {sid}, which is not in SOURCES.csv")

            resolved = False
            fragment_pinpoint = False
            for url in URL.findall(text):
                sid = url_to_id.get(normalize_url(url))
                if sid:
                    resolved = True
                    fragment_pinpoint |= bool(PAGE_FRAGMENT.search(url))
                    cited[sid] += 1
                    stats["url_refs"] += 1
                elif is_markdown:
                    unledgered.append((where, url))

            if not is_markdown:
                continue
            if UNSOURCED_TAG in line:
                stats["unsourced_tags"] += 1
                report.warn("unsourced-tag", f"{where} {clip(line.strip())}")
            dimension_text = URL.sub(" ", text)
            if DIMENSION.search(dimension_text):
                has_source = bool(line_ids.intersection(ledger_ids)) or resolved
                missing = dimension_provenance(dimension_text, has_source, fragment_pinpoint)
                if missing:
                    kind = "dimension-provenance" if has_source else "unsourced-dimension"
                    emit = report.error if strict_dimensions else report.warn
                    emit(kind, f"{where} missing {'; '.join(missing)}: {clip(line.strip())}")

    distinct = {}
    for where, url in unledgered:
        distinct.setdefault(normalize_url(url), where)
    for key, where in distinct.items():
        report.warn("unledgered-url", f"{where} {clip(key, 90)} (not in SOURCES.csv)")
    stats["unledgered_url_mentions"] = len(unledgered)

    for sid, row in ledger_ids.items():
        if not cited[sid]:
            report.warn("unreferenced-id", f"{sid} never cited ({clip(row.get('label', ''), 60)})")
    stats["ids_cited"] = sum(1 for sid in ledger_ids if cited[sid])
    return stats


def asset_target(dossier: Path, raw: str):
    """Return (path, None) for a safe dossier-relative asset path, else (None, reason).

    Checked before any file is opened: absolute/drive paths, '..' and symlinked
    components are rejected so validation never reads outside the dossier.
    """
    rel = PurePosixPath(raw.replace("\\", "/"))
    if not raw.strip() or rel.is_absolute() or PureWindowsPath(raw).anchor:
        return None, "is absolute or empty (use a dossier-relative path)"
    if any(part == ".." for part in rel.parts):
        return None, "escapes the dossier ('..')"
    current = dossier
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return None, f"goes through a symlink ({current.relative_to(dossier).as_posix()})"
    if not current.resolve().is_relative_to(dossier):
        return None, "resolves outside the dossier"
    return current, None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def saved_files(dossier: Path, report: Report):
    """Return {posix relative path} of files under assets/ and evidence/ (symlinks are errors)."""
    found = set()
    for folder in ASSET_DIRS:
        root = dossier / folder
        if root.is_symlink():
            report.error("asset-path", f"{folder}/ is a symlink; saved files must live inside the dossier")
            continue
        for current, dirs, files in os.walk(root):
            for name in dirs + files:
                path = Path(current) / name
                if path.is_symlink():
                    report.error("asset-path", f"{path.relative_to(dossier).as_posix()} is a symlink; "
                                 "save a real copy inside the dossier")
                elif name in files:
                    found.add(path.relative_to(dossier).as_posix())
            dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
    return found


def check_assets(dossier: Path, ledger_ids, report: Report):
    """Validate ASSET-INVENTORY.json against saved files and SOURCES.csv. Return stats."""
    stats = Counter()
    saved = saved_files(dossier, report)
    stats["saved_files"] = len(saved)
    inventory = dossier / INVENTORY
    if inventory.is_symlink():
        report.error("asset-inventory", f"{INVENTORY} is a symlink; keep the inventory inside the dossier")
        return stats
    if not inventory.is_file():
        if saved:
            report.error("asset-inventory", f"{INVENTORY} not found but {len(saved)} saved file(s) exist "
                         f"under assets/ or evidence/ (e.g. {sorted(saved)[0]})")
        return stats
    try:
        records = json.loads(inventory.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        report.error("asset-inventory", f"{INVENTORY} is not valid JSON: {exc}")
        return stats
    if not isinstance(records, list):
        report.error("asset-inventory", f"{INVENTORY} must be a JSON array of records")
        return stats

    listed = set()
    for index, record in enumerate(records):
        where = f"{INVENTORY}[{index}]"
        if not isinstance(record, dict):
            report.error("asset-record", f"{where} is not an object")
            continue
        bad = [f for f in ("path", "kind", "source_id", "url", "sha256")
               if not isinstance(record.get(f), str) or not record[f].strip()]
        size = record.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            bad.append("bytes")
        if isinstance(record.get("sha256"), str) and not re.fullmatch(r"[0-9a-fA-F]{64}", record["sha256"]):
            bad.append("sha256")
        if bad:
            report.error("asset-record", f"{where} missing or invalid field(s): {', '.join(dict.fromkeys(bad))} "
                         "(need path, kind, source_id, url: strings; bytes: integer; sha256: 64 hex)")
            if "path" in bad:
                continue
        raw = record["path"]
        where = f"{where} {raw}"
        sid = record.get("source_id")
        if isinstance(sid, str) and sid.strip():
            if sid not in ledger_ids:
                report.error("asset-source", f"{where}: source_id {sid} is not in SOURCES.csv")
            elif isinstance(record.get("url"), str) and \
                    normalize_url(record["url"]) != normalize_url(ledger_ids[sid].get("url", "")):
                report.error("asset-source", f"{where}: url {clip(record['url'], 70)!r} does not match "
                             f"{sid} in SOURCES.csv ({clip(ledger_ids[sid].get('url', ''), 70)!r})")
        target, reason = asset_target(dossier, raw)
        if reason:
            report.error("asset-path", f"{where}: path {reason}")
            continue
        key = target.relative_to(dossier).as_posix()
        if key in listed:
            report.error("asset-path", f"{where}: duplicate path; list each saved file once")
            continue
        listed.add(key)
        if not target.is_file():
            report.error("asset-missing", f"{where}: listed file not found in the dossier")
            continue
        stats["assets_checked"] += 1
        actual = target.stat().st_size
        if "bytes" not in bad and actual != size:
            report.error("asset-hash", f"{where}: bytes {size} recorded, file has {actual}")
        if "sha256" not in bad and sha256_file(target) != record["sha256"].lower():
            report.error("asset-hash", f"{where}: sha256 does not match the file; re-hash or re-save it")

    for rel in sorted(saved - listed):
        report.error("asset-unlisted", f"{rel} is saved but not in {INVENTORY}")
    return stats


def print_group(title, groups, limit):
    total = sum(len(v) for v in groups.values())
    print(f"\n{title} ({total})")
    for kind in sorted(groups):
        items = groups[kind]
        print(f"  [{kind}] {len(items)}")
        for message in items[:limit]:
            print(f"    - {message}")
        if len(items) > limit:
            print(f"    … and {len(items) - limit} more")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dossier", type=Path, help="dossier folder containing SOURCES.csv")
    parser.add_argument("--limit", type=int, default=10, help="items shown per category (default 10)")
    parser.add_argument("--strict-dimensions", action="store_true",
                        help="fail on missing/incomplete dimension provenance (default: warn)")
    args = parser.parse_args()

    dossier = args.dossier.expanduser().resolve()
    if not dossier.is_dir():
        parser.error(f"not a folder: {dossier}")

    report = Report()
    ledger_ids, url_to_id = check_ledger(dossier / "SOURCES.csv", report)
    stats = scan_references(dossier, ledger_ids, url_to_id, report, args.strict_dimensions)
    asset_stats = check_assets(dossier, ledger_ids, report)

    print(f"Dossier: {dossier}")
    print(
        f"Ledger: {len(ledger_ids)} valid ids; {stats['ids_cited']} cited, "
        f"{len(ledger_ids) - stats['ids_cited']} never cited"
    )
    print(
        f"Scanned: {stats['md_files']} .md, {stats['json_files']} .json; "
        f"{stats['id_refs']} S### refs, {stats['url_refs']} ledger-URL refs, "
        f"{stats['unledgered_url_mentions']} unledgered URL mentions, "
        f"{stats['unsourced_tags']} [unsourced] tags"
    )
    print(f"Assets: {asset_stats['saved_files']} saved under assets/ + evidence/; "
          f"{asset_stats['assets_checked']} inventory file(s) size/sha256-checked")
    if report.errors:
        print_group("ERRORS", report.errors, args.limit)
    if report.warnings:
        print_group("WARNINGS", report.warnings, args.limit)

    n_errors = sum(len(v) for v in report.errors.values())
    n_warnings = sum(len(v) for v in report.warnings.values())
    verdict = "FAIL" if n_errors else "PASS (with warnings)" if n_warnings else "PASS"
    print(f"\n{verdict}: {n_errors} error(s), {n_warnings} warning(s)")
    return 1 if n_errors else 0


if __name__ == "__main__":
    sys.exit(main())
