"""Artifact-bound tile review state; standard library only.

This validates recorded evidence, not whether a person actually inspected an image.
Bump SCHEMA_VERSION when check/render semantics change and old reviews must expire.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = 1


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def build_contract(pdf_sha256, page_count, pages, options):
    contract = {
        "schema_version": SCHEMA_VERSION,
        "pdf_sha256": pdf_sha256,
        "page_scope": list(range(1, page_count + 1)),
        "options": options,
        "inventory": [{"page": p["page"], "size_in": p["size_in"], "tiles": p["tiles"]}
                      for p in sorted(pages, key=lambda p: p["page"])],
    }
    digest = sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    return contract, digest


def pending_review(contract, digest):
    return {
        "schema_version": SCHEMA_VERSION,
        "pdf_sha256": contract["pdf_sha256"],
        "contract_sha256": digest,
        "pages": contract["page_scope"],
        "tiles": [{"tile": tile["tile"], "status": "pending", "issues": []}
                  for page in contract["inventory"] for tile in page["tiles"]],
    }


def load_or_create(path, template):
    """Exclusive creation: never overwrite even a partial or stale review."""
    path = Path(path)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(template, handle, indent=2)
            handle.write("\n")
    except FileExistsError:
        pass
    except OSError as exc:
        return None, f"cannot create review: {exc}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, ValueError) as exc:
        return None, f"cannot read review: {exc}"


def validate_review(contract, digest, review, automated_fail_count, load_error=None):
    errors = []
    open_issues = []
    scope = contract["page_scope"]
    inventory = contract["inventory"]
    if not scope or [p["page"] for p in inventory] != scope:
        errors.append("preflight must cover every document page exactly once")
    if not inventory or any(not p["tiles"] for p in inventory):
        errors.append("every document page must have review tiles")
    expected = [tile["tile"] for p in inventory for tile in p["tiles"]]
    if len(set(expected)) != len(expected):
        errors.append("preflight inventory has duplicate tile IDs")
    if load_error:
        errors.append(load_error)
    if not isinstance(review, dict):
        errors.append("review must be a JSON object")
        review = {}
    if type(review.get("schema_version")) is not int or review.get("schema_version") != SCHEMA_VERSION:
        errors.append("review schema version does not match")
    for key, wanted in (("pdf_sha256", contract["pdf_sha256"]), ("contract_sha256", digest)):
        if review.get(key) != wanted:
            errors.append(f"review {key} does not match this run")
    reviewed_pages = review.get("pages")
    if (not isinstance(reviewed_pages, list) or any(type(p) is not int for p in reviewed_pages)
            or sorted(reviewed_pages) != scope):
        errors.append("review pages must cover the full document exactly once")
    records = review.get("tiles")
    if not isinstance(records, list):
        errors.append("review tiles must be a list")
        records = []
    ids = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("tile"), str):
            errors.append("each tile record needs a string tile ID")
            continue
        tile = record["tile"]
        ids.append(tile)
        status, issues = record.get("status"), record.get("issues")
        if status == "pending":
            errors.append(f"{tile}: review pending")
        elif status not in ("clean", "issue"):
            errors.append(f"{tile}: status must be clean or issue")
        if not isinstance(issues, list):
            errors.append(f"{tile}: issues must be a list")
            continue
        if status == "clean" and issues:
            errors.append(f"{tile}: clean records cannot contain issues")
        if status == "issue" and not issues:
            errors.append(f"{tile}: issue records need at least one issue")
        for issue in issues:
            if (not isinstance(issue, dict) or not isinstance(issue.get("message"), str)
                    or not issue["message"].strip()):
                errors.append(f"{tile}: each issue needs a message")
                continue
            if issue.get("status") == "open":
                open_issues.append(f"{tile}: {issue['message']}")
            elif issue.get("status") == "resolved":
                if not isinstance(issue.get("resolution"), str) or not issue["resolution"].strip():
                    errors.append(f"{tile}: resolved issues need a resolution note")
            else:
                errors.append(f"{tile}: issue status must be open or resolved")
    counts = Counter(ids)
    missing, unknown = sorted(set(expected) - counts.keys()), sorted(counts.keys() - set(expected))
    duplicates = sorted(tile for tile, count in counts.items() if count != 1)
    for label, tiles in (("missing", missing), ("unknown", unknown), ("duplicate", duplicates)):
        if tiles:
            errors.append(f"{label} tile IDs: {', '.join(tiles)}")
    # A visual record can never waive a mechanical failure, even with invalid evidence.
    status = "fail" if automated_fail_count or open_issues else "incomplete" if errors else "complete"
    return {"status": status, "exit_code": {"complete": 0, "fail": 1, "incomplete": 2}[status],
            "errors": errors, "open_issues": open_issues}
