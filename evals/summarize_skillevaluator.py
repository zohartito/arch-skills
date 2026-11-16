#!/usr/bin/env python3
"""Merge SkillEvaluator Tier 1 and similarity JSON reports into one redacted JSON plus a Markdown table.

Absolute paths, evidence snippets and host details are dropped; file paths are kept relative to skills/.
"""

import argparse
import json
from pathlib import Path
import re
import sys

from eval_common import scrub_paths

SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def relative(path):
    if not path:
        return path
    parts = Path(path).parts
    if "skills" in parts:
        return "/".join(parts[len(parts) - parts[::-1].index("skills"):])
    return scrub_paths(path)


def findings(report):
    rows = []
    for group in report.get("finding_groups") or []:
        occurrences = group.get("occurrences") or [{}]
        rows.append({"severity": group.get("severity"), "category": group.get("category"),
                     "check": group.get("check_name"), "message": scrub_paths(group.get("message") or ""),
                     "file": relative(occurrences[0].get("file_path")), "line": occurrences[0].get("line_number"),
                     "occurrences": group.get("occurrence_count", len(occurrences))})
    rows.sort(key=lambda r: SEVERITY_ORDER.index(r["severity"]) if r["severity"] in SEVERITY_ORDER else 99)
    return rows


def tier1_summary(report):
    quality = (report.get("quality_summary") or [{}])[0]
    return {"skill": quality.get("skill_name") or Path(report.get("target_path") or "").name,
            "status": report.get("overall_status"), "incomplete_scans": report.get("incomplete_scans") or [],
            "quality_score": quality.get("overall_score"), "grade": quality.get("grade"),
            "dimensions": {k: v.get("score") for k, v in (quality.get("dimensions") or {}).items()},
            "severity_counts": report.get("severity_counts"), "findings": findings(report)}


def similarity_summary(report, mode):
    pairs, other = [], []
    for row in findings(report):
        match = re.match(r"'(.+)' and '(.+)' are (\w+) \(score: ([0-9.]+)\)", row["message"])
        if match:
            pairs.append({"a": match[1], "b": match[2], "class": match[3], "score": float(match[4]),
                          "severity": row["severity"]})
        else:
            other.append(row)
    pairs.sort(key=lambda p: -p["score"])
    return {"mode": mode, "status": report.get("overall_status"),
            "incomplete_scans": report.get("incomplete_scans") or [], "pairs": pairs, "other_findings": other}


def markdown(tier1, similarity, note):
    lines = [note, "", "## Tier 1 (keyless static checks)", "",
             "| Skill | Status | Quality | Critical/High/Medium/Low | Most serious finding |", "|---|---|---|---|---|"]
    for row in sorted(tier1, key=lambda r: (r["status"] == "passed", r["quality_score"] or 0)):
        counts = row["severity_counts"] or {}
        top = row["findings"][0] if row["findings"] else None
        top_text = f"{top['severity']} {top['check']}: {top['message'].splitlines()[0]}" if top else "none"
        lines.append(f"| {row['skill']} | {row['status']} | {row['quality_score']} ({row['grade']}) | "
                     f"{'/'.join(str(counts.get(k, 0)) for k in SEVERITY_ORDER[:4])} | {top_text.replace('|', '/')} |")
    for sim in similarity:
        lines += ["", f"## Similarity between skills ({sim['mode']})", "",
                  f"Status {sim['status']}; incomplete: {', '.join(sim['incomplete_scans']) or 'none'}.", "",
                  "| Pair | Class | Score |", "|---|---|---|"]
        lines += [f"| {p['a']} / {p['b']} | {p['class']} | {p['score']:.3f} |" for p in sim["pairs"]]
        lines += [f"- {o['severity']} {o['check']}: {o['message'].splitlines()[0]}" for o in sim["other_findings"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier1", type=Path, nargs="+", required=True, help="skillevaluator-tier1.json files")
    parser.add_argument("--similarity", nargs="*", default=[], metavar="MODE=FILE",
                        help="skillevaluator-similarity.json files labelled by mode, e.g. descriptions=a.json")
    parser.add_argument("--note", default="SkillEvaluator report (redacted).")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--md-out", type=Path, required=True)
    args = parser.parse_args(argv)
    for out in (args.json_out, args.md_out):
        if out.exists():
            raise SystemExit(f"{out} exists; pass a new name.")
    tier1 = [tier1_summary(json.loads(p.read_text())) for p in args.tier1]
    similarity = []
    for item in args.similarity:
        mode, _, path = item.partition("=")
        similarity.append(similarity_summary(json.loads(Path(path).read_text()), mode))
    args.json_out.write_text(json.dumps({"tier1": tier1, "similarity": similarity}, indent=2) + "\n")
    args.md_out.write_text(markdown(tier1, similarity, args.note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
