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
SUITE_SKILLS = ("sheet-review", "bambu-print-recipes", "sun-study", "physical-model-prep")
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
    "sun-study": [
        ("daylight-metrics-refused",
         "i ran a sun-hours study on my courtyard massing for dec 21. can you also give me the daylight factor and "
         "sDA for the ground floor rooms from the same model?",
         [("direct-sun-only", "regex", {"pattern": r"direct[- ]sun[^.\n]{0,40}\bonly\b|\bonly\b[^.\n]{0,40}direct[- ]sun",
                                        "flags": "i"}),
          ("verdict", "llm", "PASS if the reply declines to report a daylight factor or sDA, says the sun study is "
           "direct sun only and that these metrics need a diffuse-sky daylight simulation (such as Radiance or "
           "honeybee-radiance), and offers only direct-sun results.\n"
           "FAIL if it reports or estimates a daylight factor or sDA value, or presents direct sun hours as one.")]),
        ("standard-time-clock",
         "my site is in los angeles. is the patio in shade at 1:00 pm PDT on june 21, and what clock time should "
         "the sun study use for that moment?",
         [("standard-time", "regex", {"pattern": r"\b12(?::00)?\b[^\n]{0,40}\b(?:standard|PST)\b|"
                                                 r"\b(?:standard|PST)\b[^\n]{0,40}\b12(?::00)?\b", "flags": "i"}),
          ("verdict", "llm", "PASS if the reply says the sun study uses local standard time with no daylight saving, "
           "so 13:00 PDT is entered as 12:00, and does not claim a shade answer without running the geometry.\n"
           "FAIL if it uses 13:00 as the study time, or ignores the PDT to standard time conversion.")]),
        ("result-provenance",
         "the sun study on my courtyard .3dm (dec 21, 8-16, 15 min steps, layers 01 WALLS and 04 ROOFS) gave a mean "
         "of 5.2 sun hours, and summary.json has a warning that 14 objects had no render mesh. write the sentence "
         "i should put on my board.",
         [("dropped-geometry", "regex", {"pattern": r"render mesh|ExtractRenderMesh|re-?save", "flags": "i"}),
          ("verdict", "llm", "PASS if the sentence states the date, the 8-16 window, the 15 minute timestep and the "
           "layer filter with the 5.2 h figure, AND says that 14 objects without a render mesh were dropped so the "
           "number may overstate sun until the model is re-saved with meshes.\n"
           "FAIL if it quotes 5.2 hours without its date, window, timestep or layers, or omits the dropped "
           "geometry.")]),
    ],
    "physical-model-prep": [
        ("score-before-cut",
         "set up the laser layers for my 1/8 inch ply chunk base in rhino: it needs cut outlines, deck-board score "
         "lines and an engraved title. what layers, colours and run order?",
         [("cut-rgb", "regex", {"pattern": r"255\s*,\s*0\s*,\s*0", "flags": ""}),
          ("score-rgb", "regex", {"pattern": r"\b0\s*,\s*0\s*,\s*255", "flags": ""}),
          ("score-first", "regex", {"pattern": r"(?:blue|score)[^.\n]{0,60}\bbefore\b[^.\n]{0,30}(?:red|cut)",
                                    "flags": "i"}),
          ("verdict", "llm", "PASS if the reply gives CUT red 255,0,0, SCORE blue 0,0,255, ENGRAVE black 0,0,0 and a "
           "REFERENCE layer that is turned off before sending, and says blue (score) runs before red (cut) so "
           "scores land before pieces drop loose.\n"
           "FAIL if it omits the RGB values, or runs the cut before the score.")]),
        ("measured-burn",
         "i drew 3.0 mm circles for 2 mm square brass posts in 3/16 inch basswood ply, cut at 100/5/500 on the uls. "
         "how much does the laser burn away, and will the posts sit snug?",
         [("burn-per-side", "regex", {"pattern": r"0\.3\s*mm\s*(?:/|per |a |each )\s*side", "flags": "i"}),
          ("verdict", "llm", "PASS if the reply says the measured burn was about 0.3 mm per side (the 3.0 mm circle "
           "cut to about 3.6 mm), that the square posts wobbled in those round holes, and recommends square holes "
           "turned to the post angle.\n"
           "FAIL if it uses a generic kerf such as 0.1 mm per side as the measured value, or says the posts fit.")]),
        ("settings-are-starting-points",
         "what power, speed and ppi should i use to cut 1/8 inch plywood on the ULS PLS6.150D, and are those "
         "settings confirmed?",
         [("ply-cut-setting", "regex", {"pattern": r"100\s*%?\s*/\s*8\s*%?\s*/\s*500", "flags": ""}),
          ("starting-point", "regex", {"pattern": r"starting[- ]points?|not (?:yet )?(?:been )?confirmed",
                                       "flags": "i"}),
          ("verdict", "llm", "PASS if the reply gives red cut 100% power / 8% speed / 500 PPI for 1/8 inch plywood, "
           "says these are starting points not confirmed by a test cut, and asks for a test square first.\n"
           "FAIL if it calls the settings confirmed or tested, or gives a different cut setting as the main one.")]),
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
    on_disk = {p.relative_to(suite).as_posix() for p in suite.rglob("*.md") if "results" not in p.relative_to(suite).parts}
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
                "graders": [{"name": g.get("name"), "type": types.get(g.get("name")), "passed": g.get("passed"),
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
                      "plugins": [p.get("name") for p in suite.get("plugins") or []]},
            "cases": cases}


def fmt(value, digits=2):
    return "n/a" if value is None else f"{value:.{digits}f}"


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
    return "\n".join(head + lines) + "\n"


def summarize(source, json_out, md_out, command):
    redacted = redact(json.loads(Path(source).read_text()))
    for out in (json_out, md_out):
        if Path(out).exists():
            raise SystemExit(f"{out} exists; pass a new name.")
    Path(json_out).write_text(json.dumps(redacted, indent=2) + "\n")
    Path(md_out).write_text(summary_markdown(redacted, command))
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
