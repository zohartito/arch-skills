#!/usr/bin/env python3
"""Score first-skill routing. Partial or invalid evidence cannot pass a full suite."""

import argparse
from collections import Counter
import csv
from pathlib import Path
import sys

from eval_common import NAMESPACE, ROOT, SKILLS, public_skill
from run_triggers import INPUT, load_rows


def read_results(path, expected):
    with Path(path).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_id = {str(r["row_id"]): r for r in expected}
    seen = set()
    for row in rows:
        row_id = row.get("row_id")
        if row_id not in by_id or row_id in seen:
            raise ValueError("Results contain a duplicate or unknown row_id.")
        seen.add(row_id)
        for key in ("skill", "query", "should_trigger", "note"):
            if row.get(key) != str(by_id[row_id][key]):
                raise ValueError("Results do not match the input corpus.")
        if row.get("repository_skill_loaded") not in {"0", "1"} or not row.get("status"):
            raise ValueError("Results lack required observation fields.")
    return rows


def score(rows):
    metrics = []
    for skill in SKILLS:
        group = [r for r in rows if r["skill"] == skill]
        usable = [r for r in group if r["status"] == "ok" and str(r.get("hook_events", "0")) == "0"]
        positives = [r for r in usable if r["should_trigger"] == "1"]
        negatives = [r for r in usable if r["should_trigger"] == "0"]
        wanted = f"{NAMESPACE}:{skill}"
        hits = sum(r["first_skill"] == wanted and str(r["repository_skill_loaded"]) == "1" for r in positives)
        # Count an attempted target call on negatives even if the Skill tool failed.
        false = sum(r["first_skill"] == wanted for r in negatives)
        other = Counter(public_skill(r["first_skill"]) for r in usable if r["first_skill"] and r["first_skill"] != wanted)
        metrics.append({"skill": skill, "rows": len(group), "positive": len(positives), "negative": len(negatives),
                        "hits": hits, "false": false, "errors": len(group) - len(usable), "other": other,
                        "recall": hits / len(positives) if positives else None,
                        "false_rate": false / len(negatives) if negatives else None})
    return metrics


def verdict(metrics, complete):
    if any((m["recall"] is not None and m["recall"] < .9) or
           (m["false_rate"] is not None and m["false_rate"] > .2) for m in metrics):
        return 1
    return 0 if complete and not any(m["errors"] for m in metrics) else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="?")
    parser.add_argument("--input", type=Path, default=INPUT)
    args = parser.parse_args(argv)
    try:
        path = args.results
        if path is None:
            candidates = list((ROOT / "evals/results").glob("triggers-*.csv"))
            if not candidates:
                raise ValueError("No trigger result CSV found.")
            path = max(candidates, key=lambda p: p.stat().st_mtime_ns)
        expected = load_rows(args.input)
        rows = read_results(path, expected)
        metrics = score(rows)
        print("skill                  observed  positive  recall     negative  false rate  errors")
        for m in metrics:
            recall = f"{m['recall']:.1%}" if m["recall"] is not None else "n/a"
            false = f"{m['false_rate']:.1%}" if m["false_rate"] is not None else "n/a"
            print(f"{m['skill']:<22} {m['rows']:>3}/15    {m['positive']:>2}/10     {recall:<9} "
                  f"{m['negative']:>2}/5      {false:<10} {m['errors']}")
            if m["other"]:
                print("  other first skills: " + ", ".join(f"{s} ({n})" for s, n in sorted(m["other"].items())))
        print(f"Coverage: {len(rows)}/{len(expected)} rows. Rates exclude session errors; n/a means no usable samples.")
        print("Thresholds: recall >=90%; target false-trigger rate <=20%. First Skill call only.")
        for row in rows:
            if row["status"] != "ok":
                continue
            hit = row["first_skill"] == f"{NAMESPACE}:{row['skill']}" and row["repository_skill_loaded"] == "1"
            false = row["first_skill"] == f"{NAMESPACE}:{row['skill']}"
            if (row["should_trigger"] == "1" and not hit) or (row["should_trigger"] == "0" and false):
                print(f"Finding row {row['row_id']} ({row['skill']}): {row['query']} -> {public_skill(row['first_skill']) or '(none)'}")
        code = verdict(metrics, len(rows) == len(expected))
        print({0: "PASS: full suite meets thresholds", 1: "FAIL: observed routing threshold", 2: "INCOMPLETE: more usable evidence required"}[code])
        return code
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc if isinstance(exc, ValueError) else type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
