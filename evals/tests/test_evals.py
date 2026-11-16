"""Offline regression tests: these never invoke a real Claude session."""

import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_triggers
import eval_common as common
import make_fixture
import run_baseline
import run_triggers


def stream(*events):
    return "\n".join(json.dumps(e) for e in events)


def result(**changes):
    return {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 25,
            "usage": dict(zip(common.TOKEN_KEYS, (10, 20, 30, 40))), **changes}


def call(name="arch-eval:sheet-review", ident="call1"):
    return {"type": "assistant", "message": {"id": "msg1", "content": [
        {"type": "tool_use", "name": "Skill", "id": ident, "input": {"skill": name}}]}}


def observed(row, **changes):
    return {**row, "status": "ok", "first_skill": f"arch-eval:{row['skill']}" if row["should_trigger"] == "1" else "",
            "repository_skill_loaded": "1" if row["should_trigger"] == "1" else "0",
            "skill_calls": int(row["should_trigger"]), "hook_events": "0", **changes}


class CorpusTests(unittest.TestCase):
    def test_sixty_unique_balanced_lowercase_queries(self):
        rows = run_triggers.load_rows()
        self.assertEqual(60, len(rows))
        self.assertEqual(60, len({r["query"] for r in rows}))
        self.assertTrue(all(r["query"] == r["query"].lower() for r in rows))
        self.assertTrue(all(r["should_trigger"] == "1" for r in rows[:2]))

    def test_bad_corpus_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rows.csv"
            path.write_text("skill,query,should_trigger,note\nsheet-review,test,2,test\n")
            with self.assertRaises(ValueError):
                run_triggers.load_rows(path)


class ParserTests(unittest.TestCase):
    def test_first_skill_and_loaded_source_proof(self):
        work = Path("/tmp/example")
        text = stream(call(), {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "call1", "content": "Launching skill"}]}},
            {"type": "user", "message": {"content": "Base directory for this skill: /tmp/example/plugin/skills/sheet-review"}},
            call("arch-eval:sun-study", "call2"), result())
        row = common.parse_stream(text, work=work)
        self.assertEqual("arch-eval:sheet-review", row["first_skill"])
        self.assertEqual(1, row["repository_skill_loaded"])
        self.assertEqual(2, row["skill_calls"])
        self.assertEqual(100, row["total_tokens"])
        self.assertEqual(25, row["duration_ms"])

    def test_user_copy_does_not_count_as_repository(self):
        row = common.parse_stream(stream(call("sheet-review"), result()))
        self.assertEqual("sheet-review", row["first_skill"])
        self.assertEqual(0, row["repository_skill_loaded"])

    def test_failed_skill_not_loaded(self):
        row = common.parse_stream(stream(call(), {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "call1", "is_error": True,
             "content": "/tmp/example/plugin/skills/sheet-review"}]}}, result()), work=Path("/tmp/example"))
        self.assertEqual(1, row["failed_tool_calls"])
        self.assertEqual(0, row["repository_skill_loaded"])

    def test_duplicate_message_and_tool_error_ids(self):
        failed = {"type": "user", "uuid": "user1", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "call1", "is_error": True}]}}
        row = common.parse_stream(stream(call(), call(), failed, failed, result()))
        self.assertEqual(1, row["assistant_messages"])
        self.assertEqual(1, row["failed_tool_calls"])
        self.assertEqual(1, row["skill_calls"])
        self.assertEqual(3, row["messages"])

    def test_missing_usage_is_unknown_not_zero(self):
        row = common.parse_stream(stream(result(usage={})))
        self.assertEqual("", row["total_tokens"])

    def test_timeout_keeps_partial_evidence(self):
        row = common.parse_stream(stream(call()), timed_out=True, returncode=-9)
        self.assertEqual("timeout", row["status"])
        self.assertEqual("arch-eval:sheet-review", row["first_skill"])

    def test_usage_limit_status(self):
        for message in ("You've hit your limit", "Weekly usage limit reached", "Rate limit exceeded"):
            with self.subTest(message=message):
                row = common.parse_stream(stream(result(is_error=True, result=message)))
                self.assertEqual("usage_limit", row["status"])

    def test_skill_text_does_not_create_usage_limit(self):
        row = common.parse_stream(stream({"type": "user", "message": {"content": "usage limit guidance"}}, result()))
        self.assertEqual("ok", row["status"])

    def test_successful_limit_advice_is_not_quota_failure(self):
        for message in ("Set a weekly limit on spending.", "The print reached the bed limit.",
                        "Laser beds have a size limit; reset the origin first.", "Explain usage limits."):
            with self.subTest(message=message):
                row = common.parse_stream(stream({"type": "assistant", "message": {"content": [
                    {"type": "text", "text": message}]}}, result(result=message)))
                self.assertEqual("ok", row["status"])

    def test_structured_quota_error_and_process_error(self):
        row = common.parse_stream(stream({"type": "assistant", "error": "rate_limit", "message": {}}))
        self.assertEqual("usage_limit", row["status"])
        row = common.parse_stream("", "Rate limit exceeded", returncode=1)
        self.assertEqual("usage_limit", row["status"])
        row = common.parse_stream(stream(result(is_error=True, result="The print reached the bed limit.")))
        self.assertEqual("session_error", row["status"])

    def test_malformed_and_missing_result_are_errors(self):
        self.assertEqual("missing_result", common.parse_stream("garbage")["status"])
        self.assertEqual("malformed_stream", common.parse_stream("garbage\n" + stream(result()))["status"])
        self.assertEqual("malformed_stream", common.parse_stream("[]\n" + stream(result()))["status"])

    def test_catalog_and_hooks_without_private_names(self):
        row = common.parse_stream(stream(
            {"type": "system", "subtype": "init", "skills": [f"arch-eval:{s}" for s in common.SKILLS] + ["private-skill"]},
            {"type": "system", "subtype": "hook_started", "hook_name": "vault-context"},
            call("private-skill"), result()))
        self.assertEqual(4, row["repository_skills_listed"])
        self.assertEqual(1, row["other_catalog_entries"])
        self.assertEqual(1, row["hook_events"])
        self.assertEqual("vault", row["hook_categories"])
        self.assertNotIn("private-skill", json.dumps(row))


class ExecutionTests(unittest.TestCase):
    def test_dry_run_has_no_subprocess_or_files(self):
        with patch("subprocess.Popen", side_effect=AssertionError), patch("run_triggers.check_cli", side_effect=AssertionError):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = run_triggers.main(["--dry-run", "--limit", "4"])
            self.assertEqual(0, code)
            self.assertEqual(4, output.getvalue().count("claude -p"))
            self.assertIn("0 sessions", output.getvalue())

    def test_limit_stops_after_first_error(self):
        rows = run_triggers.load_rows()[:4]
        calls = []
        def evaluate(row):
            calls.append(row)
            return observed(row, status="usage_limit", hook_events=0)
        self.assertEqual(1, len(list(run_triggers.execute_rows(rows, evaluate))))
        self.assertEqual(1, len(calls))

    def test_no_skill_smoke_returns_incomplete(self):
        with tempfile.TemporaryDirectory() as d, patch("run_triggers.check_cli", return_value="test"), \
                patch("run_triggers.evaluate", side_effect=lambda r, _: observed(r, first_skill="", skill_calls=0, hook_events=0)):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = run_triggers.main(["--limit", "2", "--output", str(Path(d) / "results.csv")])
            self.assertEqual(2, code)
            self.assertIn("STOP", out.getvalue())

    def test_stop_after_two_no_skill_attempts(self):
        rows = run_triggers.load_rows()[:4]
        results = list(run_triggers.execute_rows(rows, lambda r: observed(r, skill_calls=0, hook_events=0)))
        self.assertEqual(2, len(results))

    def test_stop_on_hook_event(self):
        rows = run_triggers.load_rows()[:4]
        results = list(run_triggers.execute_rows(rows, lambda r: observed(r, hook_events=1)))
        self.assertEqual(1, len(results))

    def test_full_offline_schedule(self):
        rows = run_triggers.load_rows()
        for workers in (1, 2, 3):
            results = list(run_triggers.execute_rows(rows, lambda r: observed(r, hook_events=0), workers))
            self.assertEqual(list(range(1, 61)), [r["row_id"] for r in results])

    def test_staging_copies_repository_bytes(self):
        with patch("eval_common.settings", return_value={"disableAllHooks": True}):
            with common.session_workspace() as (work, hashes):
                for name in common.SKILLS:
                    staged = work / "plugin/skills" / name / "SKILL.md"
                    self.assertEqual(common.sha256(common.ROOT / "skills" / name / "SKILL.md"), common.sha256(staged))
                    self.assertEqual(hashes[name], common.sha256(staged))
                self.assertFalse(any((p / ".git").exists() for p in (work, *work.parents)))
            self.assertFalse(work.exists())

    def test_command_is_skill_only_and_disables_mcp(self):
        cmd = common.command(Path("/tmp/example"), "check this board")
        self.assertEqual("Skill", cmd[cmd.index("--tools") + 1])
        self.assertIn("--strict-mcp-config", cmd)
        self.assertNotIn("--disable-slash-commands", cmd)
        self.assertIn("--disable-slash-commands", common.command(Path("/tmp/example"), "test", disabled=True))

    def test_timeout_kills_process_group(self):
        with patch("subprocess.Popen") as popen, patch("os.killpg") as kill:
            proc = popen.return_value
            proc.communicate.side_effect = [subprocess.TimeoutExpired("claude", 120), (stream(call()), "")]
            proc.returncode = -9
            row = common.run_session(["claude"], Path("/tmp/example"))
            self.assertEqual("timeout", row["status"])
            kill.assert_called_once()

    def test_interrupt_stops_the_session_before_propagating(self):
        import sys
        import tempfile
        real_popen = subprocess.Popen
        started = []

        def sleeper(cmd, **kwargs):
            proc = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            started.append(proc)
            return proc

        with tempfile.TemporaryDirectory() as work, patch("subprocess.Popen", side_effect=sleeper), \
                patch.object(real_popen, "communicate", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                common.run_session(["claude"], Path(work))
        # The child was killed and reaped: poll() reports an exit status, not None.
        self.assertIsNotNone(started[0].poll())


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.expected = run_triggers.load_rows()
        self.rows = [observed(r) for r in self.expected]

    def test_complete_pass(self):
        self.assertEqual(0, check_triggers.verdict(check_triggers.score(self.rows), True))

    def test_checker_requires_explicit_result_path(self):
        with patch("check_triggers.read_results", side_effect=AssertionError("must not select by mtime")):
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as exc:
                check_triggers.main([])
        self.assertEqual(2, exc.exception.code)
        self.assertIn("results", err.getvalue())

    def test_recall_boundary_and_failure(self):
        positives = [r for r in self.rows if r["skill"] == "sheet-review" and r["should_trigger"] == "1"]
        positives[0]["first_skill"] = ""
        self.assertEqual(0, check_triggers.verdict(check_triggers.score(self.rows), True))
        positives[1]["first_skill"] = ""
        self.assertEqual(1, check_triggers.verdict(check_triggers.score(self.rows), True))

    def test_false_trigger_boundary_and_failure(self):
        negatives = [r for r in self.rows if r["skill"] == "sheet-review" and r["should_trigger"] == "0"]
        negatives[0]["first_skill"] = "arch-eval:sheet-review"
        self.assertEqual(0, check_triggers.verdict(check_triggers.score(self.rows), True))
        negatives[1]["first_skill"] = "arch-eval:sheet-review"
        self.assertEqual(1, check_triggers.verdict(check_triggers.score(self.rows), True))

    def test_partial_and_errors_do_not_pass(self):
        self.assertEqual(2, check_triggers.verdict(check_triggers.score(self.rows[:2]), False))
        self.rows[0]["status"] = "usage_limit"
        metrics = check_triggers.score(self.rows)
        self.assertEqual(9, metrics[0]["positive"])
        self.assertEqual(2, check_triggers.verdict(metrics, True))

    def test_other_skill_reported_and_not_hit(self):
        self.rows[0]["first_skill"] = "sun-study"
        metric = check_triggers.score(self.rows)[0]
        self.assertEqual(9, metric["hits"])
        self.assertEqual({"sun-study": 1}, metric["other"])

    def test_duplicate_results_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "results.csv"
            with path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.rows[0].keys())
                writer.writeheader()
                writer.writerows([self.rows[0], self.rows[0]])
            with self.assertRaises(ValueError):
                check_triggers.read_results(path, self.expected)


class BaselineAndFixtureTests(unittest.TestCase):
    def test_baseline_is_dry_by_default(self):
        with patch("run_baseline.check_cli", side_effect=AssertionError):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(0, run_baseline.main([]))
            self.assertEqual(2, out.getvalue().count("claude -p"))
            self.assertEqual(1, out.getvalue().count("--disable-slash-commands"))

    def test_pending_baseline_has_no_invented_metrics(self):
        report = run_baseline.render_report({}, "test", "0" * 64)
        self.assertIn("not run | n/a", report)
        self.assertIn("incomplete", report)

    def test_committed_fixture_defects(self):
        self.assertIn("PASS", make_fixture.inspect(make_fixture.DEFAULT))


if __name__ == "__main__":
    unittest.main()
