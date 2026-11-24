"""Offline CLI regressions using the real trigger corpus and checkout skill bytes."""

import contextlib
import csv
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_triggers
from eval_common import NAMESPACE, ROOT, SKILLS, sha256
from run_triggers import load_rows


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "results.csv"
        hashes = {s: sha256(ROOT / "skills" / s / "SKILL.md") for s in SKILLS}
        self.rows = [{**row, "cli_version": "offline-test", "skill_sha256": hashes[row["skill"]],
                      "status": "ok", "hook_events": "0",
                      "first_skill": f"{NAMESPACE}:{row['skill']}" if row["should_trigger"] == "1" else "",
                      "repository_skill_loaded": row["should_trigger"]} for row in load_rows()]
        self.fields = list(self.rows[0])

    def run_main(self, rows=None, *, historical=False, fields=None):
        with self.path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields if fields is not None else self.fields,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows if rows is None else rows)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_triggers.main([str(self.path)] + (["--historical"] if historical else []))
        return code, out.getvalue() + err.getvalue()

    def assert_invalid(self, *, historical=False, **kwargs):
        code, output = self.run_main(historical=historical, **kwargs)
        self.assertEqual(2, code, output)
        self.assertNotIn("PASS:", output)
        self.assertIn("HISTORICAL ERROR:" if historical else "ERROR:", output)
        return output

    def make_old_source(self):
        # Different bytes of a real repository skill, not an invented benchmark hash.
        skill = SKILLS[0]
        digest = hashlib.sha256((ROOT / "skills" / skill / "SKILL.md").read_bytes() + b"\nold revision\n").hexdigest()
        for row in self.rows:
            if row["skill"] == skill:
                row["skill_sha256"] = digest

    def test_current_complete_csv_passes(self):
        code, output = self.run_main()
        self.assertEqual(0, code, output)
        self.assertIn("Coverage: 60/60", output)
        self.assertIn("PASS: full suite", output)
        self.assertNotIn("HISTORICAL", output)

    def test_missing_metadata_columns_rejected_in_both_modes(self):
        for historical in (False, True):
            for missing in ("skill_sha256", "cli_version"):
                with self.subTest(historical=historical, missing=missing):
                    self.assert_invalid(historical=historical, fields=[f for f in self.fields if f != missing])

    def test_invalid_hashes_rejected_in_both_modes(self):
        for historical in (False, True):
            for digest in (None, "", " ", "f" * 63, "f" * 65, "g" * 64, "f" * 64 + "\n"):
                with self.subTest(historical=historical, digest=digest):
                    self.rows[0]["skill_sha256"] = digest
                    self.assert_invalid(historical=historical)

    def test_hex_case_is_not_a_different_revision(self):
        self.rows[0]["skill_sha256"] = self.rows[0]["skill_sha256"].upper()
        code, output = self.run_main()
        self.assertEqual(0, code, output)

    def test_mixed_skill_revisions_rejected_in_both_modes(self):
        self.rows[0]["skill_sha256"] = "0" * 64
        for historical in (False, True):
            with self.subTest(historical=historical):
                output = self.assert_invalid(historical=historical)
                self.assertIn("Mixed skill revisions", output)
                self.assertIn(SKILLS[0], output)

    def test_missing_or_mixed_cli_versions_rejected_in_both_modes(self):
        for historical in (False, True):
            for version in (None, "", " \t", "another-version"):
                with self.subTest(historical=historical, version=version):
                    self.rows[0]["cli_version"] = version
                    self.assert_invalid(historical=historical)

    def test_stale_revision_cannot_get_current_source_pass(self):
        self.make_old_source()
        output = self.assert_invalid()
        self.assertIn(SKILLS[0], output)
        self.assertIn("--historical", output)

    def test_changing_checkout_bytes_invalidates_previously_passing_csv(self):
        checkout = Path(self.temp.name) / "checkout"
        for skill in SKILLS:
            path = checkout / "skills" / skill / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_bytes((ROOT / "skills" / skill / "SKILL.md").read_bytes())
        with patch.object(check_triggers, "ROOT", checkout):
            code, output = self.run_main()
            self.assertEqual(0, code, output)
            path.write_bytes(path.read_bytes() + b"\nchanged description\n")
            self.assert_invalid()

    def test_missing_current_skill_is_invalid_but_historical_needs_no_checkout(self):
        with patch.object(check_triggers, "ROOT", Path(self.temp.name) / "missing-checkout"):
            output = self.assert_invalid()
            self.assertIn(SKILLS[0], output)
            code, output = self.run_main(historical=True)
            self.assertEqual(0, code, output)
            self.assertIn("HISTORICAL PASS:", output)

    def test_historical_labels_pass_fail_incomplete_and_keeps_gates(self):
        self.make_old_source()
        code, output = self.run_main(historical=True)
        self.assertEqual(0, code, output)
        self.assertIn("HISTORICAL PASS:", output)
        code, output = self.run_main(self.rows[:2], historical=True)
        self.assertEqual(2, code, output)
        self.assertIn("HISTORICAL INCOMPLETE:", output)
        for row in self.rows[:8]:
            row["first_skill"] = ""
        code, output = self.run_main(historical=True)
        self.assertEqual(1, code, output)
        self.assertIn("HISTORICAL FAIL:", output)

    def test_partial_errors_hooks_and_empty_results_stay_nonpassing(self):
        for historical in (False, True):
            for changes in ({}, {"status": "timeout"}, {"status": "usage_limit"}, {"hook_events": "1"}):
                with self.subTest(historical=historical, changes=changes):
                    rows = [{**r, **changes} for r in self.rows] if changes else self.rows[:2]
                    code, output = self.run_main(rows, historical=historical)
                    self.assertEqual(2, code, output)
                    self.assertIn("HISTORICAL INCOMPLETE:" if historical else "INCOMPLETE:", output)
                    self.assertNotIn("PASS:", output)
            self.assert_invalid(rows=[], historical=historical)

    def test_corpus_and_observation_validation_remain_required(self):
        for historical in (False, True):
            for changes in ({"row_id": 999}, {"row_id": 2}, {"skill": "private-skill"},
                            {"query": "wrong query"}, {"should_trigger": "0"}, {"note": "wrong note"},
                            {"status": ""}, {"repository_skill_loaded": ""}):
                with self.subTest(historical=historical, changes=changes):
                    self.assert_invalid(rows=[{**self.rows[0], **changes}, *self.rows[1:]], historical=historical)

    def test_lineage_diagnostics_do_not_echo_untrusted_metadata(self):
        for field in ("skill_sha256", "cli_version", "skill"):
            with self.subTest(field=field):
                private = "private-skill-at-private-path"
                output = self.assert_invalid(rows=[{**self.rows[0], field: private}, *self.rows[1:]])
                self.assertNotIn(private, output)
                self.assertNotIn(str(ROOT), output)

    def test_current_threshold_boundaries_remain_unchanged(self):
        positives = [r for r in self.rows if r["skill"] == SKILLS[0] and r["should_trigger"] == "1"]
        negatives = [r for r in self.rows if r["skill"] == SKILLS[0] and r["should_trigger"] == "0"]
        positives[0]["first_skill"] = ""
        negatives[0]["first_skill"] = f"{NAMESPACE}:{SKILLS[0]}"
        code, output = self.run_main()
        self.assertEqual(0, code, output)  # 90% recall, 20% false-trigger rate.
        for row, first in ((positives[1], ""), (negatives[1], f"{NAMESPACE}:{SKILLS[0]}")):
            with self.subTest(should_trigger=row["should_trigger"]):
                previous = row["first_skill"]
                row["first_skill"] = first
                code, output = self.run_main()
                self.assertEqual(1, code, output)
                self.assertIn("FAIL:", output)
                row["first_skill"] = previous

    def test_committed_partial_and_error_records_never_pass(self):
        names = ("triggers-2026-11-15.csv", "triggers-after-fix-rows59-60-retry.csv",
                 "triggers-full-after-fix.csv", "triggers-full-rows15-60.csv", "triggers-full.csv")
        for name in names:
            path = ROOT / "evals/results" / name
            self.assertTrue(path.is_file())
            for historical in (False, True):
                with self.subTest(result=path.name, historical=historical):
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = check_triggers.main([str(path)] + (["--historical"] if historical else []))
                    self.assertNotEqual(0, code, out.getvalue())
                    self.assertNotIn("PASS:", out.getvalue())
                    if historical:
                        self.assertIn("HISTORICAL", out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
