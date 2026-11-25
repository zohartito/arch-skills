"""Offline tests for the `claude plugin eval` suite builder and the result summarizers. No Claude session starts."""

import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eval_common
import plugin_eval
import summarize_skillevaluator as skilleval

PROMPT_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
               "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}
GRADER_TYPES = {"regex", "tool_used", "tool_order", "file_exists", "llm", "baseline"}


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, text
    return dict(line.split(": ", 1) for line in match[1].splitlines())


def cases(files):
    return sorted({Path(relative).parent for relative in files if relative.endswith("prompt.md")})


PATH_CASES = [
    ("/workspace/private-project/report.pdf", "<path>"),
    ("/root/a", "<path>"),
    ("/home/u/b", "<path>"),
    ("/Users/u/c", "<path>"),
    ("/private/tmp/eval/report.json", "<path>"),
    ("/var/folders/xx/report.json", "<path>"),
    (r"C:\Users\u\x", "<path>"),
    ("D:/data/x", "<path>"),
    (r"\\server\share\x", "<path>"),
    ("~/private/report.pdf", "<path>"),
    ("/abs/arch-skills/skills/sun-study/SKILL.md", "<repo>/skills/sun-study/SKILL.md"),
    (f"/abs/{eval_common.ROOT.name}/evals/report.json", "<repo>/evals/report.json"),
    (r"C:\work\arch-skills\skills\sun-study\SKILL.md", "<repo>/skills/sun-study/SKILL.md"),
    (r"\\server\share\arch-skills\evals\report.json", "<repo>/evals/report.json"),
    ("~/arch-skills/evals/report.json", "<repo>/evals/report.json"),
    ("/abs/not-arch-skills/report.pdf", "<path>"),
    ("/abs/arch-skills", "<path>"),
]
UNCHANGED_TEXT = [
    "https://github.com/zohartito/arch-skills",
    "https://example.com/report?next=/workspace/private/report.pdf",
    "skills/sun-study/SKILL.md",
    "./skills/sun-study/SKILL.md",
    "../skills/sun-study/SKILL.md",
    "1/2", "2026/11/15", "and/or", "a /b",
    "prefix/workspace/private/report.pdf",
    "prefix~/private/report.pdf",
    r"prefixC:\Users\u\x",
    r"folder\C:\Users\u\x",
]


class PathScrubTests(unittest.TestCase):
    def test_shared_scrubber_handles_absolute_path_formats(self):
        for path, expected in PATH_CASES:
            with self.subTest(path=path):
                self.assertEqual(eval_common.scrub_paths(path), expected)

    def test_preserves_non_path_text(self):
        for text in UNCHANGED_TEXT:
            with self.subTest(text=text):
                self.assertEqual(eval_common.scrub_paths(text), text)

    def test_token_boundaries_and_trailing_punctuation(self):
        for path, expected in PATH_CASES:
            for before, after in [("failed to open ", "."), ('file="', '", retry'),
                                  ("(", ")"), ("[", "]"), ("file:", "; retry"), ("`", "`")]:
                with self.subTest(path=path, before=before, after=after):
                    self.assertEqual(eval_common.scrub_paths(before + path + after), before + expected + after)

    def test_scrubs_multiple_paths_without_changing_a_url(self):
        text = r"Compare /workspace/private/report.pdf, C:\data\report.pdf and https://example.com/a/b."
        self.assertEqual(eval_common.scrub_paths(text),
                         "Compare <path>, <path> and https://example.com/a/b.")

    def test_non_strings_are_returned_unchanged(self):
        for value in (None, 0, False, [], {}, Path("/workspace/private/report.pdf")):
            with self.subTest(value=value):
                self.assertIs(eval_common.scrub_paths(value), value)


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.files = plugin_eval.expected_files()

    def test_every_trigger_row_and_content_case_is_present(self):
        names = [case.name for case in cases(self.files)]
        self.assertEqual(len(names), len(set(names)))
        for skill in plugin_eval.SUITE_SKILLS:
            own = [n for n in names if n.startswith(skill)]
            self.assertEqual(sum("-pos-" in n for n in own), 10)
            self.assertEqual(sum("-neg-" in n for n in own), 5)
            self.assertGreaterEqual(sum("-content-" in n for n in own), 2)
            self.assertGreaterEqual(len(own), 6)

    def test_prompt_frontmatter_uses_only_documented_keys(self):
        for case in cases(self.files):
            meta = frontmatter(self.files[f"{case}/prompt.md"])
            self.assertLessEqual(set(meta), PROMPT_KEYS, case)
            self.assertEqual(meta["allowed_tools"], "[Skill]")

    def test_every_case_has_graders_of_documented_types(self):
        for case in cases(self.files):
            graders = [r for r in self.files if r.startswith(f"{case}/graders/")]
            self.assertTrue(graders, case)
            for relative in graders:
                self.assertIn(frontmatter(self.files[relative])["type"], GRADER_TYPES)

    def test_smoke_tag_selects_six_cases(self):
        smoke = [c.name for c in cases(self.files) if "smoke" in frontmatter(self.files[f"{c}/prompt.md"])["tags"]]
        self.assertEqual(sorted(smoke), sorted(plugin_eval.SMOKE))

    def test_skill_pattern_matches_namespaced_call_only_for_that_skill(self):
        pattern = re.compile(plugin_eval.skill_pattern("sheet-review"))
        self.assertTrue(pattern.search(json.dumps({"skill": "arch-skills:sheet-review"})))
        self.assertTrue(pattern.search(json.dumps({"skill": "sheet-review"})))
        self.assertFalse(pattern.search(json.dumps({"skill": "arch-skills:sun-study"})))

    def test_negative_cases_forbid_the_skill_in_both_arms(self):
        text = self.files["sheet-review/sheet-review-neg-r45/graders/skill-not-fired.md"]
        meta = frontmatter(text)
        self.assertEqual((meta["min"], meta["max"], meta["arm"]), ("0", "0", "both"))

    def test_content_regexes_accept_the_skill_answer_and_reject_a_generic_one(self):
        samples = {
            "hairline-limit": ("strokes under 0.1 pt may vanish", "hairlines are usually fine"),
            "text-limit": ("keep text at 6 pt or larger", "keep text legible"),
            "not-checked-column": ("Not checked: tiles r2c3, r4c1", "everything reviewed"),
            "xy-distance": ("raise support/object XY distance to 1.0 mm", "increase support density"),
            "upside-down": ("print them upside down, seat on the bed", "print upright with tree supports"),
            "nozzle": ("use the 0.2 mm nozzle", "use a fine nozzle"),
            "layer": ("0.08 mm layers", "0.12 mm layers"),
        }
        for skill, content in plugin_eval.CONTENT.items():
            for _slug, _prompt, graders in content:
                for name, kind, spec in graders:
                    if kind != "regex":
                        continue
                    good, bad = samples[name]
                    pattern = re.compile(spec["pattern"], re.I if "i" in spec.get("flags", "") else 0)
                    self.assertTrue(pattern.search(good), name)
                    self.assertFalse(pattern.search(bad), name)

    def test_regex_grader_frontmatter_round_trips_the_pattern(self):
        text = self.files["bambu-print-recipes/bambu-print-recipes-content-railing-supports/graders/xy-distance.md"]
        self.assertEqual(json.loads(frontmatter(text)["pattern"]), r"XY[^\n]{0,60}1(?:\.0)?\s*mm")

    def test_check_detects_stale_and_unknown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = Path(tmp)
            plugin_eval.build(suite)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(plugin_eval.check(suite), 0)
                (suite / "sheet-review/sheet-review-pos-r01/prompt.md").write_text("changed\n")
                (suite / "sheet-review/extra.md").write_text("x\n")
                out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(plugin_eval.check(suite), 1)
            self.assertIn("out of date: sheet-review/sheet-review-pos-r01/prompt.md", out.getvalue())
            self.assertIn("sheet-review/extra.md", out.getvalue())

    def test_committed_suite_matches_the_builder(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(plugin_eval.check(), 0)


AGGREGATE = {
    "schemaVersion": 1, "claudeVersion": "2.1.325", "durationSeconds": 9, "costUsd": 0.01, "partial": False,
    "suite": {"root": "/Users/someone/repo", "ablation": "with-without", "modelOverride": "haiku",
              "judgeModel": "haiku", "plugins": [{"name": "arch-skills", "path": "/Users/someone/repo"}]},
    "aggregates": {"casesTotal": 1, "casesPassed": 1, "overallScore": 1, "meanDelta": 1},
    "cases": [{"name": "c1", "dir": "evals/plugin-eval/x/c1", "promptMarkdown": "secret prompt", "maxTurns": 8,
               "graders": [{"name": "verdict", "type": "llm"}, {"name": "skill-fired", "type": "tool_used"}],
               "aggregates": {"score": 1, "scoreWithout": 0, "delta": 1},
               "arms": {"with": [{"score": 1, "passed": True, "turns": 3, "costUsd": 0.004, "judgeCostUsd": 0.001,
                                  "error": "timed out in /private/tmp/e-abc/out", "tracePath": "/private/tmp/t.jsonl",
                                  "graders": [{"name": "verdict", "passed": True, "explanation": "judge votes",
                                               "evidence": "model reply text", "judgeVotes": [True, True, True]},
                                              {"name": "skill-fired", "passed": True, "scored": False}]}],
                        "without": [{"score": 0, "passed": False, "turns": 1, "costUsd": 0.002, "graders": []}]}}],
}


class SummaryTests(unittest.TestCase):
    def test_error_paths_are_scrubbed_in_json_and_markdown(self):
        for path, expected in PATH_CASES:
            with self.subTest(path=path):
                error = f"failed to open {path}."
                clean_error = f"failed to open {expected}."
                self.assertEqual(plugin_eval.scrub(error), clean_error)
                source = {"cases": [{"name": "error-case", "arms": {"with": [{"error": error}]}}]}
                redacted = plugin_eval.redact(source)
                self.assertEqual(redacted["cases"][0]["arms"]["with"][0]["error"], clean_error)
                self.assertNotIn(path, json.dumps(redacted))
                self.assertIn(clean_error, plugin_eval.summary_markdown(redacted, "offline"))

    def test_redact_drops_text_and_paths(self):
        redacted = plugin_eval.redact(AGGREGATE)
        dumped = json.dumps(redacted)
        for private in ("/Users/", "/private/", "model reply text", "secret prompt", "tracePath"):
            self.assertNotIn(private, dumped)
        run = redacted["cases"][0]["arms"]["with"][0]
        self.assertEqual(run["error"], "timed out in <path>")
        self.assertEqual([g["type"] for g in run["graders"]], ["llm", "tool_used"])
        self.assertEqual(redacted["suite"]["plugins"], ["arch-skills"])

    def test_markdown_lists_scores_and_cost(self):
        text = plugin_eval.summary_markdown(plugin_eval.redact(AGGREGATE), "claude plugin eval .")
        self.assertIn("| c1 | 1.00 | 0.00 | 1.00 |", text)
        self.assertIn("skill-fired pass (indicator)", text)
        self.assertIn("0.0070", text)

    def test_summarize_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "aggregate.json")
            source.write_text(json.dumps(AGGREGATE))
            existing = Path(tmp, "out.json")
            existing.write_text("{}")
            with self.assertRaises(SystemExit):
                plugin_eval.summarize(source, existing, Path(tmp, "out.md"), "cmd")


SMOKE_JSON = plugin_eval.ROOT / "evals/results/plugin-eval-2026-11-15.json"


def run(passed, graders=None, **extra):
    graders = [{"name": "verdict", "type": "llm", "passed": passed}] if graders is None else graders
    return {"passed": passed, "graders": graders, **extra}


def case(name, without, with_):
    return {"name": name, "graders": [{"name": "verdict", "type": "llm"}],
            "arms": {"with": with_ if isinstance(with_, list) else [with_],
                     "without": without if isinstance(without, list) else [without]}}


class PairedOutcomeTests(unittest.TestCase):
    def outcomes(self, *cases):
        return plugin_eval.paired_outcomes(plugin_eval.redact({"cases": list(cases)}))

    def test_saved_smoke_json_separates_content_gains_from_invalid_routing_pairs(self):
        groups = plugin_eval.paired_outcomes(plugin_eval.redact(json.loads(SMOKE_JSON.read_text())))
        content, routing = groups["content"], groups["routing"]
        self.assertEqual((content["eligible"], content["observed"]), (2, 2))
        self.assertEqual([content[k] for k in "GRFH"], [2, 0, 0, 0])
        self.assertEqual(content["excluded"], [])
        self.assertEqual((routing["eligible"], routing["observed"]), (4, 2))
        self.assertEqual([routing[k] for k in "GRFH"], [1, 0, 0, 1])
        self.assertEqual(sorted(e["case"] for e in routing["excluded"]), ["sheet-review-neg-r45", "sheet-review-pos-r01"])
        self.assertTrue(all("maximum number of turns" in e["reason"] for e in routing["excluded"]))

    def test_all_four_transitions_and_pass_rate_change(self):
        g = self.outcomes(case("a-content-g", run(False), run(True)), case("a-content-r", run(True), run(False)),
                          case("a-content-f", run(False), run(False)), case("a-content-h", run(True), run(True)),
                          case("a-content-g2", run(False), run(True)))["content"]
        self.assertEqual([g[k] for k in "GRFH"], [2, 1, 1, 1])
        self.assertEqual((g["observed"], g["net"], g["ppChange"]), (5, 1, 20.0))

    def test_zero_gains_reports_negative_change(self):
        g = self.outcomes(case("a-content-r", run(True), run(False)), case("a-content-h", run(True), run(True)))["content"]
        self.assertEqual((g["G"], g["R"], g["net"], g["ppChange"]), (0, 1, -1, -50.0))

    def test_invalid_and_unpaired_cases_are_excluded_and_listed(self):
        cases = [case("a-content-none", run(None), run(True)),
                 case("a-content-str", run(False), run("yes")),
                 case("a-content-err", run(False), run(True, error="boom in /private/tmp/x")),
                 case("a-content-abort", run(False), run(True, aborted=True)),
                 case("a-content-skip", run(False), run(True, skippedPaidGraders=True)),
                 case("a-content-ungraded", run(False, []), run(True)),
                 case("a-content-grader-none", run(False, [{"name": "verdict", "passed": None}]), run(True)),
                 case("a-content-mismatch", run(False, [{"name": "other", "type": "regex", "passed": False}]), run(True)),
                 case("a-content-missing", [], run(True)),
                 case("a-content-repeat", [run(False), run(True)], run(True)),
                 case("a-content-dup", run(False), run(True)), case("a-content-dup", run(True), run(False))]
        g = self.outcomes(*cases)["content"]
        self.assertEqual((g["eligible"], g["observed"], g["G"] + g["R"] + g["F"] + g["H"]), (11, 0, 0))
        self.assertIsNone(g["ppChange"])
        reasons = {e["case"]: (e["kind"], e["reason"]) for e in g["excluded"]}
        self.assertEqual(len(reasons), 11)
        self.assertEqual(reasons["a-content-err"], ("invalid", "with error: boom in <path>"))
        self.assertEqual(reasons["a-content-abort"], ("invalid", "with aborted"))
        self.assertEqual(reasons["a-content-skip"], ("invalid", "with skipped grading"))
        self.assertIn("not boolean", reasons["a-content-none"][1])
        self.assertIn("not boolean", reasons["a-content-str"][1])
        self.assertEqual(reasons["a-content-ungraded"], ("invalid", "without grading incomplete"))
        self.assertEqual(reasons["a-content-grader-none"], ("invalid", "without grading incomplete"))
        self.assertEqual(reasons["a-content-mismatch"][1], "scored graders differ between arms")
        self.assertEqual(reasons["a-content-missing"], ("unpaired", "missing arm: without"))
        self.assertEqual(reasons["a-content-repeat"][0], "unpaired")
        self.assertEqual(reasons["a-content-dup"], ("unpaired", "duplicate case id (2 entries)"))

    def test_raw_and_redacted_inputs_agree_and_keep_grader_types(self):
        raw = json.loads(SMOKE_JSON.read_text())
        once = plugin_eval.redact(raw)
        twice = plugin_eval.redact(once)
        self.assertEqual(twice, once)
        self.assertEqual(plugin_eval.paired_outcomes(twice), plugin_eval.paired_outcomes(once))
        fresh = plugin_eval.redact(AGGREGATE)
        self.assertEqual(plugin_eval.redact(fresh), fresh)
        self.assertEqual([g["type"] for g in fresh["cases"][0]["arms"]["with"][0]["graders"]], ["llm", "tool_used"])

    def test_summarize_writes_paired_section_to_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_json, out_md = Path(tmp, "s.json"), Path(tmp, "s.md")
            plugin_eval.summarize(SMOKE_JSON, out_json, out_md, "offline")
            saved = json.loads(out_json.read_text())
            self.assertEqual(saved["pairedOutcomes"]["content"]["G"], 2)
            text = out_md.read_text()
            self.assertIn("| content | 2 | 2 | 1.00 | 2 | 0 | 0 | 0 | 2 | 100.0 |", text)
            self.assertIn("| routing | 4 | 2 | 0.50 | 1 | 0 | 0 | 1 | 1 | 50.0 |", text)
            self.assertIn("routing / sheet-review-pos-r01 (invalid): with error: exit 1: Reached maximum", text)


TIER1 = {
    "target_path": "/Users/someone/repo/skills/sun-study", "overall_status": "failed", "incomplete_scans": [],
    "severity_counts": {"critical": 0, "high": 1, "medium": 1, "low": 0},
    "quality_summary": [{"skill_name": "sun-study", "overall_score": 86.8, "grade": "B",
                         "dimensions": {"correctness": {"score": 80.0}}}],
    "finding_groups": [
        {"severity": "medium", "category": "QUALITY", "check_name": "q", "message": "No examples",
         "occurrences": [{"file_path": "/Users/someone/repo/skills/sun-study/SKILL.md", "line_number": None}]},
        {"severity": "high", "category": "SCHEMA", "check_name": "yaml_syntax", "message": "Invalid YAML\nline 2",
         "occurrences": [{"file_path": "/Users/someone/repo/skills/sun-study/SKILL.md", "line_number": 2}]},
    ],
}
SIMILARITY = {"overall_status": "incomplete", "incomplete_scans": ["collection-coverage"], "finding_groups": [
    {"severity": "medium", "category": "SIMILARITY", "check_name": "SIMILAR",
     "message": "'a-skill' and 'b-skill' are SIMILAR (score: 0.777)", "occurrences": [{"file_path": "a-skill"}]},
    {"severity": "high", "category": "SIMILARITY", "check_name": "HIGH_SIMILARITY",
     "message": "'c-skill' and 'd-skill' are HIGH_SIMILARITY (score: 0.919)", "occurrences": [{"file_path": "c"}]},
]}


class SkillEvaluatorSummaryTests(unittest.TestCase):
    def test_finding_messages_and_fallback_files_use_shared_path_scrubbing(self):
        for path, expected in PATH_CASES:
            with self.subTest(path=path):
                report = {**TIER1, "finding_groups": [
                    {"severity": "high", "check_name": "file_error", "message": f"failed to open {path}.",
                     "occurrences": [{"file_path": path}]},
                ]}
                summary = skilleval.tier1_summary(report)
                finding = summary["findings"][0]
                self.assertEqual(finding["message"], f"failed to open {expected}.")
                # Preserve relative()'s existing native-path behavior: start after the last skills/ component.
                expected_file = "sun-study/SKILL.md" if "skills" in Path(path).parts else expected
                self.assertEqual(finding["file"], expected_file)
                self.assertIn(f"failed to open {expected}.", skilleval.markdown([summary], [], "offline"))

    def test_relative_keeps_existing_skills_behavior(self):
        for path in ("/abs/arch-skills/skills/sun-study/SKILL.md", "skills/sun-study/SKILL.md",
                     "/abs/skills/nested/skills/sun-study/SKILL.md"):
            with self.subTest(path=path):
                self.assertEqual(skilleval.relative(path), "sun-study/SKILL.md")

    def test_finding_messages_preserve_non_path_text(self):
        for text in UNCHANGED_TEXT:
            with self.subTest(text=text):
                rows = skilleval.findings({"finding_groups": [{"message": text}]})
                self.assertEqual(rows[0]["message"], text)

    def test_tier1_summary_sorts_by_severity_and_strips_paths(self):
        summary = skilleval.tier1_summary(TIER1)
        self.assertEqual(summary["findings"][0]["check"], "yaml_syntax")
        self.assertEqual(summary["findings"][0]["file"], "sun-study/SKILL.md")
        self.assertNotIn("/Users/", json.dumps(summary))
        self.assertEqual(summary["dimensions"], {"correctness": 80.0})

    def test_similarity_pairs_are_parsed_and_ranked(self):
        summary = skilleval.similarity_summary(SIMILARITY, "descriptions")
        self.assertEqual([(p["a"], p["score"]) for p in summary["pairs"]], [("c-skill", 0.919), ("a-skill", 0.777)])
        self.assertEqual(summary["other_findings"], [])

    def test_markdown_puts_failing_skills_first(self):
        passing = {**TIER1, "overall_status": "passed", "target_path": "/x/skills/sheet-review",
                   "quality_summary": [{"skill_name": "sheet-review", "overall_score": 80, "grade": "B"}]}
        text = skilleval.markdown([skilleval.tier1_summary(passing), skilleval.tier1_summary(TIER1)],
                                  [skilleval.similarity_summary(SIMILARITY, "descriptions")], "note")
        rows = [line for line in text.splitlines() if line.startswith("| s")]
        self.assertTrue(rows[0].startswith("| sun-study | failed"))
        self.assertIn("| c-skill / d-skill | HIGH_SIMILARITY | 0.919 |", text)


if __name__ == "__main__":
    unittest.main()
