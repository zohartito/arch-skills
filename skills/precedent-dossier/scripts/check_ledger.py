#!/usr/bin/env python3
"""Validate a precedent dossier: SOURCES.csv integrity and citations in its notes.

Hard errors (exit 1): missing required columns, malformed or duplicate source ids,
non-http(s) URLs, empty label/date/class, and notes citing ids absent from the ledger.
Warnings (exit 0): ledger rows never cited, inline URLs not in the ledger, number+unit
lines with no source on the same line, boilerplate qualifications, duplicate URLs.

Markdown links whose URL is a ledger row count as citations of that row, so dossiers
that cite by inline URL (e.g. older dossiers) can be checked too.
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
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
UNSOURCED_TAG = "[unsourced]"
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


def scan_references(dossier: Path, ledger_ids, url_to_id, report: Report):
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
            for url in URL.findall(text):
                sid = url_to_id.get(normalize_url(url))
                if sid:
                    resolved = True
                    cited[sid] += 1
                    stats["url_refs"] += 1
                elif is_markdown:
                    unledgered.append((where, url))

            if not is_markdown:
                continue
            if UNSOURCED_TAG in line:
                stats["unsourced_tags"] += 1
                report.warn("unsourced-tag", f"{where} {clip(line.strip())}")
            if DIMENSION.search(URL.sub(" ", text)) and not line_ids and not resolved:
                report.warn("unsourced-dimension", f"{where} {clip(line.strip())}")

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
    args = parser.parse_args()

    dossier = args.dossier.expanduser().resolve()
    if not dossier.is_dir():
        parser.error(f"not a folder: {dossier}")

    report = Report()
    ledger_ids, url_to_id = check_ledger(dossier / "SOURCES.csv", report)
    stats = scan_references(dossier, ledger_ids, url_to_id, report)

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
