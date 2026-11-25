"""Offline completion-gate regression and optional real-CLI baseline comparison.

python evals/tests/test_review_gate.py --baseline PATH/TO/OLD/pdf_preflight.py
The old CLI runs the same PDFs/settings without the new review flags: its actual
exit code is the automated-only acceptance baseline, not a simulated validator.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/sheet-review/scripts"
sys.path.insert(0, str(SCRIPTS))
import review_state

PREFLIGHT = SCRIPTS / "pdf_preflight.py"
FIXTURE = ROOT / "evals/fixtures/sheet-review.pdf"
BASELINE = None
# Low rendering resolution keeps these protocol tests fast; it is not a visual-quality eval.
OPTIONS = ["--expect-size", "11x8.5", "--overview-dpi", "9", "--tile-dpi", "12"]


def clean(template):
    state = copy.deepcopy(template)
    for tile in state["tiles"]:
        tile["status"] = "clean"
    return state


class ReviewStateTests(unittest.TestCase):
    def test_contract_covers_inventory_and_is_order_independent(self):
        pages = [{"page": 1, "size_in": [11, 8.5],
                  "tiles": [{"tile": "p1-r1c1.png", "bbox_in": [0, 0, 11, 8.5]}]}]
        options = {"tile_dpi": 150, "min_ppi": 150}
        contract, digest = review_state.build_contract("artifact", 1, pages, options)
        self.assertEqual(digest, review_state.build_contract("artifact", 1, pages, dict(reversed(list(options.items()))))[1])
        pages[0]["tiles"][0]["bbox_in"][2] = 10
        self.assertNotEqual(digest, review_state.build_contract("artifact", 1, pages, options)[1])
        self.assertEqual([1], contract["page_scope"])

    def test_every_check_render_option_changes_contract(self):
        options = {"expect_size": None, "palette": [], "pages": [1], "compare_sha256": None,
                   "min_ppi": 150, "min_text_pt": 6, "min_stroke_pt": .1, "overview_dpi": 30,
                   "tile_dpi": 150, "tile_in": 6, "overlap_in": .5, "compare_dpi": 50, "no_tiles": False}
        digest = review_state.build_contract("artifact", 1, [], options)[1]
        for option in options:
            with self.subTest(option=option):
                changed = {**options, option: "changed"}
                self.assertNotEqual(digest, review_state.build_contract("artifact", 1, [], changed)[1])

    def test_empty_inventory_cannot_vacuously_pass(self):
        contract, digest = review_state.build_contract("artifact", 0, [], {})
        state = clean(review_state.pending_review(contract, digest))
        self.assertEqual("incomplete", review_state.validate_review(contract, digest, state, 0)["status"])


class PreflightReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix=".review-test-", dir=ROOT)
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        code, cls.report = cls.run_cli("initial")
        if code != 0:
            raise AssertionError(f"initial automated-only exit: {code}")
        cls.template = cls.report["pending_review"]
        cls.clean = clean(cls.template)

    @classmethod
    def run_cli(cls, label, *, pdf=FIXTURE, extra=(), state=None, strict=False, baseline=False, review_path=None):
        out = cls.work / label
        if review_path is None:
            review_path = cls.work / f"{label}-review.json"
        if state is not None:
            review_path.write_text(json.dumps(state), encoding="utf-8")
        script = BASELINE if baseline else PREFLIGHT
        command = [sys.executable, str(script), str(pdf), "--out", str(out), *OPTIONS, *extra]
        if not baseline:
            command += ["--review", str(review_path)]
            if strict:
                command += ["--require-review"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60,
                                env={**os.environ, "PYTHONUTF8": "1"}, cwd=ROOT)
        report_path = out / "report.json"
        if not report_path.exists():
            raise AssertionError(f"CLI produced no report (exit {result.returncode}): {result.stderr}")
        return result.returncode, json.loads(report_path.read_text(encoding="utf-8"))

    def test_pending_template_and_existing_findings(self):
        self.assertEqual({"FAIL": 0, "WARN": 2, "INFO": 0}, self.report["counts"])
        self.assertEqual(["hairline-strokes", "small-text"], [f["check"] for f in self.report["findings"]])
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), self.report["pdf_sha256"])
        self.assertEqual([1, 2], self.report["review_contract"]["page_scope"])
        self.assertEqual(8, len(self.template["tiles"]))
        self.assertTrue(all(t["status"] == "pending" for t in self.template["tiles"]))
        self.assertEqual("incomplete", self.report["review"]["status"])
        code, report = self.run_cli("pending-strict", strict=True)
        self.assertEqual(2, code)
        self.assertEqual("incomplete", report["review"]["status"])

    def test_clean_review_passes_and_is_not_overwritten(self):
        path = self.work / "completed.json"
        original = json.dumps(self.clean, indent=4).encode("utf-8")
        path.write_bytes(original)
        code, report = self.run_cli("clean", strict=True, review_path=path)
        self.assertEqual(0, code)
        self.assertEqual("complete", report["review"]["status"])
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(self.report["review_contract_sha256"], report["review_contract_sha256"])
        self.assertEqual(self.report["findings"], report["findings"])
        # A stale review remains untouched too: use a new file to restart a review.
        code, _ = self.run_cli("stale-preserved", strict=True, review_path=path, extra=["--tile-dpi", "13"])
        self.assertEqual(2, code)
        self.assertEqual(original, path.read_bytes())
        if BASELINE:
            baseline_code, baseline_report = self.run_cli("baseline-clean", baseline=True)
            self.assertEqual(0, baseline_code)
            self.assertEqual(baseline_report["findings"], report["findings"])
            print("\nClean control: baseline=0 candidate=0; identical findings (0 FAIL, 2 WARN)")

    def test_rejection_matrix(self):
        cases = []

        def case(name, mutate, status="incomplete"):
            state = copy.deepcopy(self.clean)
            mutate(state)
            cases.append((name, state, FIXTURE, [], status))

        case("missing-tile", lambda s: s["tiles"].pop())
        case("duplicate-tile", lambda s: s["tiles"].append(copy.deepcopy(s["tiles"][0])))
        case("unknown-tile", lambda s: s["tiles"][0].update(tile="p99-r1c1.png"))
        case("wrong-pdf-hash", lambda s: s.update(pdf_sha256="0" * 64))
        case("wrong-contract", lambda s: s.update(contract_sha256="0" * 64))
        case("partial-review-pages", lambda s: s.update(pages=[1]))
        case("duplicate-review-pages", lambda s: s.update(pages=[1, 1, 2]))
        case("unknown-review-page", lambda s: s.update(pages=[1, 2, 3]))
        case("empty-records", lambda s: s.update(tiles=[]))
        case("pending-tile", lambda s: s["tiles"][0].update(status="pending"))
        case("invalid-status", lambda s: s["tiles"][0].update(status="approved"))
        case("issue-without-evidence", lambda s: s["tiles"][0].update(status="issue"))
        case("open-issue", lambda s: s["tiles"][0].update(status="issue", issues=[
            {"message": "stray line across drawing", "status": "open"}]), "fail")
        case("clean-cannot-hide-issue", lambda s: s["tiles"][0].update(issues=[
            {"message": "stray line across drawing", "status": "open"}]), "fail")
        case("resolution-needs-note", lambda s: s["tiles"][0].update(status="issue", issues=[
            {"message": "suspect line", "status": "resolved"}]))
        case("invalid-record-type", lambda s: s["tiles"].__setitem__(0, []))
        case("invalid-issue-status", lambda s: s["tiles"][0].update(status="issue", issues=[
            {"message": "suspect line", "status": "waived"}]))
        changed = self.work / "changed.pdf"
        changed.write_bytes(FIXTURE.read_bytes() + b"\n% changed export bytes\n")
        cases.append(("changed-pdf", self.clean, changed, [], "incomplete"))
        for name, extra in (
            ("changed-render", ["--tile-dpi", "13"]),
            ("changed-check", ["--min-ppi", "149"]),
            ("changed-palette", ["--palette", "#123456"]),
            ("changed-compare", ["--compare", str(FIXTURE)]),
            ("changed-inventory", ["--tile-in", "7"]),
        ):
            cases.append((name, self.clean, FIXTURE, extra, "incomplete"))
        # Even a freshly bound all-clean review cannot bless partial/no-tile runs.
        for name, extra in (("partial-preflight", ["--pages", "1"]), ("no-tiles", ["--no-tiles"]),
                            ("automated-fail", ["--expect-size", "36x24"])):
            _, report = self.run_cli(f"prepare-{name}", extra=extra)
            cases.append((name, clean(report["pending_review"]), FIXTURE, extra,
                          "fail" if name == "automated-fail" else "incomplete"))
        rejected = baseline_rejected = 0
        for name, state, pdf, extra, status in cases:
            with self.subTest(case=name):
                code, report = self.run_cli(name, pdf=pdf, extra=extra, state=state, strict=True)
                self.assertEqual({"fail": 1, "incomplete": 2}[status], code)
                self.assertEqual(status, report["review"]["status"])
                rejected += code in (1, 2)
                if BASELINE:
                    baseline_code, baseline_report = self.run_cli(f"baseline-{name}", pdf=pdf, extra=extra, baseline=True)
                    self.assertIn(baseline_code, (0, 1))
                    baseline_rejected += baseline_code == 1
                    self.assertEqual(baseline_report["findings"], report["findings"])
        if BASELINE:
            print(f"\nInvalid-completion rejection: baseline={baseline_rejected}/{len(cases)}; "
                  f"candidate={rejected}/{len(cases)}; findings identical in every pair")
        self.assertEqual(len(cases), rejected)

    def test_equivalent_options_and_comparison_content_binding(self):
        code, report = self.run_cli("equivalent-options", state=self.clean, strict=True, extra=[
            "--min-ppi", "150", "--tile-in", "6", "--min-text-pt", "6", "--pages", "2,1",
            "--expect-size", "8.5x11"])
        self.assertEqual(0, code)
        self.assertEqual(self.report["review_contract_sha256"], report["review_contract_sha256"])
        # Exercise every option through argparse and report construction, not just the helper.
        for name, value in (("min-stroke-pt", ".2"), ("overview-dpi", "10"), ("overlap-in", ".25"),
                            ("compare-dpi", "51"), ("min-text-pt", "5.5")):
            with self.subTest(option=name):
                code, _ = self.run_cli(f"option-{name}", state=self.clean, strict=True, extra=[f"--{name}", value])
                self.assertEqual(2, code)
        previous = self.work / "previous.pdf"
        previous.write_bytes(FIXTURE.read_bytes())
        _, report = self.run_cli("compare-initial", extra=["--compare", str(previous)])
        state = clean(report["pending_review"])
        previous.write_bytes(FIXTURE.read_bytes() + b"\n% changed previous export\n")
        code, _ = self.run_cli("compare-changed", state=state, strict=True, extra=["--compare", str(previous)])
        self.assertEqual(2, code)

    def test_resolved_issue_requires_documented_disposition(self):
        state = copy.deepcopy(self.clean)
        state["tiles"][0].update(status="issue", issues=[{"message": "suspected stray line", "status": "resolved",
                                                       "resolution": "Confirmed intentional boundary in unchanged PDF"}])
        code, report = self.run_cli("resolved", state=state, strict=True)
        self.assertEqual(0, code)
        self.assertEqual("complete", report["review"]["status"])

    def test_bad_json_and_legacy_mode(self):
        path = self.work / "malformed.json"
        path.write_text("{broken", encoding="utf-8")
        for strict, expected in ((True, 2), (False, 0)):
            code, report = self.run_cli(f"malformed-{strict}", review_path=path, strict=strict)
            self.assertEqual(expected, code)
            self.assertEqual("incomplete", report["review"]["status"])
            self.assertEqual("{broken", path.read_text(encoding="utf-8"))
        for state in ([], {**self.clean, "tiles": None}, {**self.clean, "pages": [True, 2]}):
            with self.subTest(state=state):
                code, _ = self.run_cli("bad-shape", state=state, strict=True)
                self.assertEqual(2, code)

    def test_invalid_geometry_and_output_alias_are_rejected_before_writing(self):
        out = self.work / "invalid-arguments"
        out.mkdir()
        protected = out / "report.json"
        protected.write_text("existing review", encoding="utf-8")
        for extra in (["--overlap-in", "6"], ["--tile-in", "nan"], ["--pages", "0"],
                      ["--pages", "1,1"], ["--review", str(protected)]):
            with self.subTest(extra=extra):
                result = subprocess.run([sys.executable, str(PREFLIGHT), str(FIXTURE), "--out", str(out), *extra],
                                        capture_output=True, timeout=30, cwd=ROOT)
                self.assertEqual(2, result.returncode)
                self.assertEqual("existing review", protected.read_text(encoding="utf-8"))


if __name__ == "__main__":
    if "--baseline" in sys.argv:
        index = sys.argv.index("--baseline")
        BASELINE = Path(sys.argv[index + 1]).resolve()
        del sys.argv[index:index + 2]
        if not BASELINE.is_file():
            raise SystemExit("baseline script does not exist")
    unittest.main()
