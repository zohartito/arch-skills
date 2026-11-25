#!/usr/bin/env python3
"""Build the `claude plugin eval` suite and summarize its results without starting Claude.

  build      write evals/plugin-eval/ from triggers.csv rows plus the content cases below
  check      exit 1 if the files on disk differ from what `build` would write
  summarize  turn an aggregate-result.json into a redacted JSON and a Markdown table
"""

import argparse
import json
from pathlib import Path
import sys

from eval_common import ROOT, scrub_paths as scrub
from run_triggers import load_rows

SUITE = ROOT / "evals/plugin-eval"
SUITE_SKILLS = ("sheet-review", "bambu-print-recipes")
SMOKE = {"sheet-review-pos-r01", "sheet-review-neg-r45", "sheet-review-content-hairline-small-text",
         "bambu-print-recipes-pos-r04", "bambu-print-recipes-neg-r48", "bambu-print-recipes-content-railing-supports"}

CONTENT = {
    "sheet-review": [
        ("hairline-small-text",
         "my exported 36x24 board pdf has some linework at 0.05 pt and a few labels set at 5 pt. "
         "will those print, and what limits should i hold them to?",
         [("hairline-limit", "regex", {"pattern": r"0\.1\s*pt", "flags": "i"}),
          ("text-limit", "regex", {"pattern": r"\b6\s*(?:pt|point)", "flags": "i"}),
          ("verdict", "llm", "PASS if the reply says the 0.05 pt strokes are hairlines below 0.1 pt that may vanish "
           "in print AND says the 5 pt labels are below a 6 pt minimum text size.\n"
           "FAIL if it says either one is fine as is, or gives no numeric limit for one of them.")]),
        ("placed-scale",
         "in my indesign board a floor plan labelled 1/8\" = 1'-0\" is placed at 85%. the exported pdf looks fine. "
         "is the sheet ready to submit?",
         [("verdict", "llm", "PASS if the reply says the drawing no longer matches its stated 1/8\" = 1'-0\" scale "
           "because it is placed at 85%, and that the label must be recomputed or the drawing placed at 100% "
           "before the sheet is called ready.\n"
           "FAIL if it calls the sheet ready, or treats the 85% placement as harmless.")]),
        ("review-status",
         "i checked most tiles of my board but skipped two, and the preflight shows one FAIL for a font that is "
         "not embedded. write the review status i should send my partner.",
         [("not-checked-column", "regex", {"pattern": r"not checked", "flags": "i"}),
          ("verdict", "llm", "PASS if the status says the sheet is NOT ready, names the open font-embedding FAIL "
           "and the two unreviewed tiles, and separates what a script verified from what was seen by eye and "
           "what was not checked.\n"
           "FAIL if it calls the sheet ready or done, or omits the FAIL or the skipped tiles.")]),
    ],
    "bambu-print-recipes": [
        ("garden-table-orientation",
         "how should i orient the 1/8 inch garden table and benches on the a1 bed, and do they need supports?",
         [("upside-down", "regex", {"pattern": r"upside[- ]down|(?:top|seat)s?\b[^.\n]{0,30}\b(?:down|on the (?:bed|plate))",
                                    "flags": "i"}),
          ("verdict", "llm", "PASS if the reply says to print the table and benches upside down (top or seat on the "
           "bed) with no supports.\n"
           "FAIL if it prints them upright on their legs, or recommends supports under them.")]),
        ("railing-supports",
         "tree supports keep touching the terrace railing pickets on my house walls print. "
         "what do i change in bambu studio?",
         [("xy-distance", "regex", {"pattern": r"XY[^\n]{0,60}1(?:\.0)?\s*mm", "flags": "i"}),
          ("verdict", "llm", "PASS if the reply recommends build plate only, a larger support/object XY distance "
           "(about 1.0 mm), and support painting Block or a support blocker over the pickets, AND says that if the "
           "preview still shows contact the geometry should change instead of trying more settings.\n"
           "FAIL if it only suggests generic support tweaks (density, angle, interface) or never mentions changing "
           "the geometry.")]),
        ("scale-figures",
         "what nozzle and layer height should i use for 1/4 inch scale people and dogs on the a1?",
         [("nozzle", "regex", {"pattern": r"0\.2\s*mm\s*nozzle|0\.2\s*nozzle|nozzle[^\n]{0,30}0\.2\b", "flags": "i"}),
          ("layer", "regex", {"pattern": r"0\.08", "flags": ""}),
          ("verdict", "llm", "PASS if the reply recommends a 0.2 mm nozzle with about 0.08 mm layers, and "
           "build-plate-only tree supports only under overhangs such as the dogs' bellies.\n"
           "FAIL if it recommends the 0.4 mm nozzle as the main choice, or layers of 0.12 mm or more.")]),
    ],
}


def quoted(text):
    return json.dumps(text, ensure_ascii=False)


def skill_pattern(skill):
    return '"skill"\\s*:\\s*"(?:[\\w-]+:)?' + skill + '"'


def prompt_file(description, tags, max_turns, prompt):
    return (f"---\ndescription: {quoted(description)}\ntags: [{', '.join(tags)}]\n"
            f"max_turns: {max_turns}\ntimeout_seconds: 180\nallowed_tools: [Skill]\n---\n\n{prompt}\n")


def skill_grader(skill, fired=True):
    lines = ["---", "type: tool_used", "tool: Skill", f"input_match: '{skill_pattern(skill)}'"]
    if not fired:
        lines += ["min: 0", "max: 0", "arm: both"]
    return "\n".join(lines + ["---", ""])


def grader_file(kind, spec):
    if kind == "llm":
        return f"---\ntype: llm\n---\n\n{spec}\n"
    lines = ["---", "type: regex", f"pattern: {quoted(spec['pattern'])}"]
    if spec.get("flags"):
        lines.append(f"flags: {spec['flags']}")
    return "\n".join(lines + ["---", ""])


def expected_files(rows=None):
    rows = load_rows() if rows is None else rows
    files = {}
    for skill in SUITE_SKILLS:
        for row in (r for r in rows if r["skill"] == skill):
            positive = row["should_trigger"] == "1"
            name = f"{skill}-{'pos' if positive else 'neg'}-r{int(row['row_id']):02d}"
            tags = ["trigger", "positive" if positive else "negative", skill] + (["smoke"] if name in SMOKE else [])
            base = f"{skill}/{name}"
            files[f"{base}/prompt.md"] = prompt_file(f"triggers.csv row {row['row_id']}: {row['note']}",
                                                     tags, 8, row["query"])
            grader = "skill-fired" if positive else "skill-not-fired"
            files[f"{base}/graders/{grader}.md"] = skill_grader(skill, positive)
        for slug, prompt, graders in CONTENT[skill]:
            name = f"{skill}-content-{slug}"
            tags = ["content", skill] + (["smoke"] if name in SMOKE else [])
            base = f"{skill}/{name}"
            files[f"{base}/prompt.md"] = prompt_file(f"content check: {slug}", tags, 6, prompt)
            files[f"{base}/graders/skill-fired.md"] = skill_grader(skill)
            for grader_name, kind, spec in graders:
                files[f"{base}/graders/{grader_name}.md"] = grader_file(kind, spec)
    return files


def build(suite=SUITE):
    for relative, text in expected_files().items():
        path = suite / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return 0


def check(suite=SUITE):
    expected = expected_files()
    on_disk = {str(p.relative_to(suite)) for p in suite.rglob("*.md") if "results" not in p.relative_to(suite).parts}
    stale = sorted(r for r, text in expected.items() if not (suite / r).is_file() or (suite / r).read_text() != text)
    extra = sorted(on_disk - set(expected))
    for relative in stale:
        print(f"out of date: {relative}")
    for relative in extra:
        print(f"not generated (remove by hand): {relative}")
    return 1 if stale or extra else 0


def redact(result):
    """Keep scores, verdicts, turns, cost and versions; drop prompts, replies, judge evidence and local paths."""
    def run(entry, types):
        return {"score": entry.get("score"), "passed": entry.get("passed"), "turns": entry.get("turns"),
                "costUsd": entry.get("costUsd"), "judgeCostUsd": entry.get("judgeCostUsd"),
                "durationSeconds": entry.get("durationSeconds"), "error": scrub(entry.get("error")),
                "aborted": bool(entry.get("aborted")), "skippedPaidGraders": bool(entry.get("skippedPaidGraders")),
                "graders": [{"name": g.get("name"), "type": types.get(g.get("name")) or g.get("type"),
                             "passed": g.get("passed"),
                             "scored": g.get("scored", True), "judgeVotes": g.get("judgeVotes")}
                            for g in entry.get("graders") or []]}
    cases = []
    for case in result.get("cases") or []:
        types = {g.get("name"): g.get("type") for g in case.get("graders") or []}
        arms = {arm: [run(r, types) for r in runs] for arm, runs in (case.get("arms") or {}).items()}
        cases.append({"name": case.get("name"), "dir": case.get("dir"), "maxTurns": case.get("maxTurns"),
                      "aggregates": case.get("aggregates"), "arms": arms})
    suite = result.get("suite") or {}
    keep_suite = ("ablation", "modelOverride", "judgeModel", "tagFilters", "caseFilters", "threshold",
                  "concurrency", "runsOverride")
    keep = ("schemaVersion", "claudeVersion", "startedAt", "durationSeconds", "costUsd", "partial",
            "partialReason", "aggregates")
    return {**{k: result.get(k) for k in keep if k in result},
            "suite": {**{k: suite[k] for k in keep_suite if k in suite},
                      "plugins": [p.get("name") if isinstance(p, dict) else p for p in suite.get("plugins") or []]},
            "cases": cases}


def fmt(value, digits=2):
    return "n/a" if value is None else f"{value:.{digits}f}"


TRANSITIONS = {(False, True): "G", (True, False): "R", (False, False): "F", (True, True): "H"}


def pair_problem(case, content):
    """Return (kind, reason) when a case is not one valid with/without pair, else None."""
    arms = case.get("arms") or {}
    counts = {arm: len(arms.get(arm) or []) for arm in ("with", "without")}
    if 0 in counts.values():
        return "unpaired", "missing arm: " + ", ".join(a for a, n in counts.items() if n == 0)
    if any(n > 1 for n in counts.values()):
        return "unpaired", f"ambiguous repeats: {counts['with']} with / {counts['without']} without runs"
    runs = {arm: arms[arm][0] for arm in counts}
    for arm, run in runs.items():
        if run.get("error"):
            return "invalid", f"{arm} error: {run['error']}"
        if run.get("aborted"):
            return "invalid", f"{arm} aborted"
        if run.get("skippedPaidGraders"):
            return "invalid", f"{arm} skipped grading"
        if not isinstance(run.get("passed"), bool):
            return "invalid", f"{arm} outcome not boolean: {run.get('passed')!r}"
    if content:
        scored = {}
        for arm, run in runs.items():
            graders = [g for g in run.get("graders") or [] if g.get("scored", True)]
            if not graders or any(not isinstance(g.get("passed"), bool) for g in graders):
                return "invalid", f"{arm} grading incomplete"
            scored[arm] = sorted((str(g.get("name")), str(g.get("type"))) for g in graders)
        if scored["with"] != scored["without"]:
            return "invalid", "scored graders differ between arms"
    return None


def paired_outcomes(redacted):
    """Classify each case as G (gain), R (regression), F (fails both), H (holds both) from one run per arm."""
    cases = redacted.get("cases") or []
    names = [c.get("name") for c in cases]
    groups = {g: {"eligible": 0, "observed": 0, "G": 0, "R": 0, "F": 0, "H": 0, "excluded": []}
              for g in ("content", "routing")}
    seen = set()
    for case in cases:
        name = case.get("name")
        content = "-content-" in str(name)
        group = groups["content" if content else "routing"]
        if name in seen:
            continue
        seen.add(name)
        group["eligible"] += 1
        dupes = names.count(name)
        problem = ("unpaired", f"duplicate case id ({dupes} entries)") if dupes > 1 else pair_problem(case, content)
        if problem:
            group["excluded"].append({"case": name, "kind": problem[0], "reason": problem[1]})
            continue
        group["observed"] += 1
        group[TRANSITIONS[case["arms"]["without"][0]["passed"], case["arms"]["with"][0]["passed"]]] += 1
    for group in groups.values():
        n = group["observed"]
        group["coverage"] = n / group["eligible"] if group["eligible"] else None
        group["net"] = group["G"] - group["R"]
        group["ppChange"] = 100 * group["net"] / n if n else None
    return groups


def paired_markdown(groups):
    lines = ["", "## Paired outcomes", "",
             "One valid run per arm. G: failed without the skill, passed with it. R (regression): passed without, "
             "failed with. F: failed both. H: passed both. Pass-rate change is (G-R)/observed in percentage points.",
             "", "| Group | Eligible | Observed | Coverage | G | R | F | H | G-R | Pass-rate change, pp |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, g in groups.items():
        lines.append(f"| {name} | {g['eligible']} | {g['observed']} | {fmt(g['coverage'])} | {g['G']} | {g['R']} | "
                     f"{g['F']} | {g['H']} | {g['net']} | {fmt(g['ppChange'], 1)} |")
    excluded = [(name, e) for name, g in groups.items() for e in g["excluded"]]
    if excluded:
        lines += ["", "Excluded from paired counts:"]
        lines += [f"- {name} / {e['case']} ({e['kind']}): {e['reason']}" for name, e in excluded]
    return lines


def summary_markdown(redacted, command):
    lines = ["| Case | With | Without | Δ | Graders, with-arm first run | Turns with/without | Cost USD |",
             "|---|---|---|---|---|---|---|"]
    for case in redacted["cases"]:
        with_runs = case["arms"].get("with") or [{}]
        without_runs = case["arms"].get("without") or [{}]
        graders = ", ".join(f"{g['name']} {'pass' if g['passed'] else 'fail'}{'' if g['scored'] else ' (indicator)'}"
                            for g in with_runs[0].get("graders", []))
        errors = [r["error"] for arm in case["arms"].values() for r in arm if r.get("error")]
        if errors:
            graders += f"; run error: {errors[0]}"
        agg = case.get("aggregates") or {}
        cost = sum((r.get("costUsd") or 0) + (r.get("judgeCostUsd") or 0) for arm in case["arms"].values() for r in arm)
        lines.append(f"| {case['name']} | {fmt(agg.get('score'))} | {fmt(agg.get('scoreWithout'))} | "
                     f"{fmt(agg.get('delta'))} | {graders} | {with_runs[0].get('turns')}/{without_runs[0].get('turns')} | "
                     f"{fmt(cost, 4)} |")
    agg = redacted.get("aggregates") or {}
    suite = redacted.get("suite") or {}
    head = [f"Command: `{command}`", "",
            f"Claude Code {redacted.get('claudeVersion')}; agent model {suite.get('modelOverride') or 'default'}, "
            f"judge {suite.get('judgeModel') or 'default'}; ablation {suite.get('ablation')}; "
            f"{len(redacted['cases'])} cases; overall with-arm score {fmt(agg.get('overallScore'))}; "
            f"mean Δ {fmt(agg.get('meanDelta'))}; cases passed {agg.get('casesPassed')}/{agg.get('casesTotal')}; "
            f"estimated list-price cost ${fmt(redacted.get('costUsd'), 4)}; "
            f"{fmt(redacted.get('durationSeconds'), 0)} s; partial: {redacted.get('partial')}.", ""]
    return "\n".join(head + lines + paired_markdown(paired_outcomes(redacted))) + "\n"


def summarize(source, json_out, md_out, command):
    redacted = redact(json.loads(Path(source).read_text()))
    redacted["pairedOutcomes"] = paired_outcomes(redacted)
    for out in (json_out, md_out):
        if Path(out).exists():
            raise SystemExit(f"{out} exists; pass a new name.")
    Path(json_out).write_text(json.dumps(redacted, indent=2) + "\n")
    Path(md_out).write_text(summary_markdown(redacted, command), encoding="utf-8")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("build")
    sub.add_parser("check")
    s = sub.add_parser("summarize")
    s.add_argument("aggregate", type=Path)
    s.add_argument("--json-out", type=Path, required=True)
    s.add_argument("--md-out", type=Path, required=True)
    s.add_argument("--command", default="claude plugin eval .")
    args = parser.parse_args(argv)
    if args.action == "build":
        return build()
    if args.action == "check":
        return check()
    return summarize(args.aggregate, args.json_out, args.md_out, args.command)


if __name__ == "__main__":
    sys.exit(main())
