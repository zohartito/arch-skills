#!/usr/bin/env python3
"""Offline CLI regressions. Run from repo root:

python -m unittest discover -s skills/precedent-dossier/tests -v
python skills/precedent-dossier/tests/test_check_ledger.py --compare BASELINE_SCRIPT

The comparison runs both actual validators on the same synthetic dossiers, not mocks.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "skills/precedent-dossier/scripts/check_ledger.py"
URL = "https://example.org/plan.pdf"
TABLE = """## Dimensions

| What | Value | Source + sheet | Written or scaled (scale) |
|---|---|---|---|
"""

# Each case is a complete Markdown line/row (not just a regex fragment).
INCOMPLETE = {
    "bare_id": "Width 3 m [S001]",
    "written_no_pinpoint": "Width 3 m [S001, written]",
    "pinpoint_no_marker": "Width 3 m [S001 p.3]",
    "scaled_no_scale": "Width 3 m [S001 p.3, scaled]",
    "scale_no_marker": "Width 3 m [S001 p.3, 1:100]",
    "scaled_no_pinpoint": "Width 3 m [S001, scaled 1:100]",
    "scaled_placeholder": "Width 3 m [S001 p.3, scaled TBD]",
    "scaled_zero": "Width 3 m [S001 p.3, scaled 1:0]",
    "timestamp_is_not_scale": "Width 3 m [S001 timestamp 1:30, scaled]",
    "scaled_negative": "Width 3 m [S001 p.3, scaled -1:100]",
    "scaled_missing_denominator": "Width 3 m [S001 p.3, scaled 1:]",
    "derived_source_only": "Area 12 m² [derived: S001]",
    "derived_punctuation_only": "Area 12 m² [derived: ---] [S001]",
    "derived_empty": "Area 12 m² [derived: ] [S001]",
    "derived_label_only": "Area 12 m² [derived] [S001]",
    "derived_no_inputs": "Area 12 m² [derived: length times width]",
    "derived_unledgered_url": "Area 12 m² [derived: length times width] [plan](https://example.org/other)",
    "derived_placeholder": "Area 12 m² [derived: TBD] [S001]",
    "table_no_pinpoint": TABLE + "| Width | 3 m | [S001] | written |",
    "table_no_method": TABLE + "| Width | 3 m | [S001 p.3] | |",
    "table_no_scale": TABLE + "| Width | 3 m | [S001 sheet A101] | scaled |",
    "legacy_bare_url": f"Width 3 m [plan]({URL})",
    "legacy_no_pinpoint": f"Width 3 m [plan, written]({URL})",
    "legacy_no_method": f"Width 3 m [plan p.3]({URL})",
    "unknown_pinpoint": "Width 3 m [S001 p.?, written]",
    "generic_reported": "Reported area 12 m² [S001]",
    "published_no_source": "Published figure: area 12 m²",
    "no_source": "Width 3 m",
    "url_words_not_evidence": "Width 3 m [S001] https://example.org/p.3/written",
}
VALID = {
    "written_page": "Width 3 m [S001 p.3, written]",
    "written_sheet": "Width 3 m [S001 sheet A101, written]",
    "written_figure": "Width 3 m [S001 fig.4, written]",
    "written_timestamp": "Width 3 m [S001 timestamp 01:34, written]",
    "scaled_ratio": "Width 3 m [S001 p.3, scaled 1:100]",
    "scaled_at": "Width 3 m [S001 fig.4, scaled at 1:50]",
    "scaled_separate_scale": "Width 3 m [S001 timestamp 1:30, scaled; scale 1:50]",
    "scaled_decimal": "Width 3 m [S001 p.3, scaled 0.5:50]",
    "scaled_unicode": "Width 10 ft [S001 p.3, scaled 1/8″ = 1′-0″]",
    "scaled_imperial": "Width 10 ft [S001 p.3, scaled 1/8\"=1'-0\"]",
    "scaled_metric": "Width 3 m [S001 p.3, scaled 1 cm = 1 m]",
    "derived": "Area 12 m² [derived: length times width] [S001 p.3; S002 p.4]",
    "derived_url": f"Area 12 m² [derived: subtract courtyard from footprint] [plan]({URL})",
    "derived_unicode_method": "Area 12 m² [derived: אורך כפול רוחב] [S001]",
    "derived_table_plain_method": TABLE + "| Area | 12 m² | [S001] | derived: length times width |",
    "written_imperial": "Width 10'-0\" [S001 p.3, written]",
    "written_metric_mm": "Width 300 mm [S001 p.3, written]",
    "written_area_ft2": "Area 1200 ft² [S001 p.3, written]",
    "written_page_range": "Width 3 m [S001 pp.3–4, written]",
    "legacy_trailing_slash": f"Width 3 m [plan p.3, written]({URL}/)",
    "published": "Published figure: area 1200 sf [S001] (not a measurement)",
    "published_plural": "Published figures: 1200 sf [S001]; 1300 sf [S002]",
    "table_written": TABLE + "| Width | 3 m | [S001 p.3] | written |",
    "table_scaled": TABLE + "| Width | 3 m | [S001 sheet A101] | scaled 1:100 |",
    "table_derived": TABLE + "| Area | 12 m² | [S001 p.3; S002 p.4] | [derived: length times width] |",
    "table_published": TABLE + "| Area | 1200 sf | [S001] | published figure, not a measurement |",
    "legacy_written": f"Width 3 m [plan p.3, written]({URL})",
    "legacy_scaled": f"Width 3 m [plan sheet A101]({URL}) — scaled 1:100",
    "legacy_fragment": f"Width 3 m [plan]({URL}#page=3), written",
    "legacy_published": f"Published figure: area 1200 sf [project]({URL})",
    "mixed_case": "Width 3 m [S001 PAGE 3, WRITTEN]",
}


def make_dossier(folder, note, suffix=".md"):
    with (folder / "SOURCES.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_id", "url", "label", "access_date_local", "source_class",
                         "qualification", "evidence_route"])
        for sid, url in [("S001", URL), ("S002", "https://example.org/section.pdf")]:
            writer.writerow([sid, url, "Test plan", "2026-01-01", "architect project source",
                             "Written dimensions only; as-built not confirmed", "test fixture"])
    (folder / ("note" + suffix)).write_text(note + "\n", encoding="utf-8")
    # Keep unused ledger rows from obscuring the dimension-specific assertions.
    (folder / "index.md").write_text("Sources: [S001; S002]\n", encoding="utf-8")


def run_check(note, strict=False, checker=CHECKER, suffix=".md"):
    # All generated files stay in this worktree, including on the Windows test host.
    with tempfile.TemporaryDirectory(prefix="ledger-test-", dir=ROOT) as tmp:
        folder = Path(tmp)
        make_dossier(folder, note, suffix)
        return subprocess.run(
            [sys.executable, str(checker), str(folder), *(["--strict-dimensions"] if strict else [])],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=15,
        )


def has_dimension_finding(result):
    return any(f"[{kind}]" in result.stdout
               for kind in ("unsourced-dimension", "dimension-provenance"))


class DimensionCases(unittest.TestCase):
    def test_incomplete_provenance_warns_without_failing_by_default(self):
        for name, note in INCOMPLETE.items():
            with self.subTest(case=name):
                result = run_check(note)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertTrue(has_dimension_finding(result), result.stdout)
                self.assertIn("WARNINGS", result.stdout)
                self.assertIn("note.md:", result.stdout)

    def test_incomplete_provenance_fails_in_strict_mode(self):
        for name, note in INCOMPLETE.items():
            with self.subTest(case=name):
                result = run_check(note, strict=True)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertTrue(has_dimension_finding(result), result.stdout)
                self.assertIn("ERRORS", result.stdout)

    def test_valid_controls_have_no_findings_in_either_mode(self):
        for name, note in VALID.items():
            for strict in (False, True):
                with self.subTest(case=name, strict=strict):
                    result = run_check(note, strict=strict)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertIn("PASS: 0 error(s), 0 warning(s)", result.stdout)

    def test_unknown_ids_remain_errors_in_either_mode(self):
        for strict in (False, True):
            for note in ("Architect [S999]", "Width 3 m [S999 p.3, written]",
                         "Area 12 m² [derived: length times width] [S001; S999]"):
                with self.subTest(strict=strict, note=note):
                    result = run_check(note, strict=strict)
                    self.assertEqual(1, result.returncode)
                    self.assertIn("[missing-id]", result.stdout)

    def test_non_dimension_and_fenced_lines_stay_ignored(self):
        for note in ("Architect [S001]", f"[Plan]({URL}?width=3m) [S001]",
                     "```text\nWidth 3 m [S999]\n```", "Lane S001-S099"):
            with self.subTest(note=note):
                result = run_check(note, strict=True)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertFalse(has_dimension_finding(result), result.stdout)

    def test_json_checks_ids_but_not_dimensions(self):
        result = run_check('{"dimension": "3 m", "source_id": "S001"}', strict=True, suffix=".json")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(has_dimension_finding(result))
        result = run_check('{"source_id": "S999"}', strict=True, suffix=".json")
        self.assertEqual(1, result.returncode)
        self.assertIn("[missing-id]", result.stdout)

    def test_diagnostics_explain_the_missing_evidence(self):
        cases = (("written_no_pinpoint", "source pinpoint"),
                 ("pinpoint_no_marker", "written/scaled marker"),
                 ("scaled_no_scale", "explicit scale"),
                 ("derived_empty", "nonempty [derived: method]"),
                 ("derived_no_inputs", "ledgered source/input"))
        for name, message in cases:
            with self.subTest(case=name):
                result = run_check(INCOMPLETE[name], strict=True)
                self.assertEqual(1, result.returncode)
                self.assertIn(message, result.stdout)

    def test_legacy_urls_still_count_as_ledger_citations(self):
        result = run_check(VALID["legacy_fragment"], strict=True)
        self.assertIn("1 ledger-URL refs", result.stdout)
        self.assertNotIn("[unledgered-url]", result.stdout)

    def test_ledger_integrity_errors_are_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="ledger-test-", dir=ROOT) as tmp:
            folder = Path(tmp)
            make_dossier(folder, VALID["written_page"])
            ledger = folder / "SOURCES.csv"
            # The fixture is owned by this test; corrupt an existing URL deliberately.
            text = ledger.read_text(encoding="utf-8")
            ledger.write_text(text.replace(URL, "file:///plan.pdf"), encoding="utf-8")
            for strict in (False, True):
                result = subprocess.run(
                    [sys.executable, str(CHECKER), str(folder),
                     *(["--strict-dimensions"] if strict else [])],
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(1, result.returncode)
                self.assertIn("[ledger-url]", result.stdout)

    def test_other_warnings_remain_warnings_in_strict_mode(self):
        result = run_check("Unknown source https://example.org/other [unsourced]", strict=True)
        self.assertEqual(0, result.returncode)
        self.assertIn("[unledgered-url]", result.stdout)
        self.assertIn("[unsourced-tag]", result.stdout)


PDF = b"%PDF-1.4 test plan\n"


def asset_record(**overrides):
    record = {"path": "assets/00-plan.pdf", "kind": "drawing", "source_id": "S001", "url": URL,
              "bytes": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}
    return {**record, **overrides}


class AssetCases(unittest.TestCase):
    """ASSET-INVENTORY.json is checked against saved files and the ledger."""

    def run_assets(self, inventory=None, files=("assets/00-plan.pdf",), setup=None):
        with tempfile.TemporaryDirectory(prefix="ledger-test-", dir=ROOT) as tmp:
            folder = Path(tmp) / "dossier"
            folder.mkdir()
            make_dossier(folder, "Plan [S001; S002]")
            for rel in files:
                (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                (folder / rel).write_bytes(PDF)
            if inventory is not None:
                text = inventory if isinstance(inventory, str) else json.dumps(inventory)
                (folder / "ASSET-INVENTORY.json").write_text(text, encoding="utf-8")
            if setup:
                setup(folder)
            return subprocess.run([sys.executable, str(CHECKER), str(folder), "--strict-dimensions"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=15)

    def test_valid_inventory_and_legacy_dossier_pass(self):
        for inventory, files in (([asset_record()], ("assets/00-plan.pdf",)), (None, ())):
            with self.subTest(inventory=inventory):
                result = self.run_assets(inventory, files)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("PASS: 0 error(s)", result.stdout)

    def test_bad_inventories_fail_with_diagnostics(self):
        cases = {
            "malformed_json": ("[{", "[asset-inventory]", "not valid JSON"),
            "not_array": ({"path": "assets/00-plan.pdf"}, "[asset-inventory]", "JSON array"),
            "missing_inventory": (None, "[asset-inventory]", "not found"),
            "missing_file": ([asset_record(), asset_record(path="assets/01-gone.pdf")],
                             "[asset-missing]", "assets/01-gone.pdf"),
            "unlisted_file": ([], "[asset-unlisted]", "assets/00-plan.pdf is saved"),
            "wrong_bytes": ([asset_record(bytes=1)], "[asset-hash]", "bytes 1 recorded"),
            "wrong_hash": ([asset_record(sha256="0" * 64)], "[asset-hash]", "sha256 does not match"),
            "bad_field": ([asset_record(bytes="19", kind="")], "[asset-record]", "kind, bytes"),
            "duplicate_path": ([asset_record(), asset_record(path="assets\\00-plan.pdf")],
                               "[asset-path]", "duplicate path"),
            "unknown_source": ([asset_record(source_id="S999")], "[asset-source]", "S999 is not in"),
            "url_mismatch": ([asset_record(url="https://example.org/other.pdf")],
                             "[asset-source]", "does not match S001"),
            "escaping_path": ([asset_record(), asset_record(path="../SOURCES.csv")],
                              "[asset-path]", "escapes the dossier"),
            "absolute_path": ([asset_record(), asset_record(path=str(ROOT / "README.md"))],
                              "[asset-path]", "is absolute"),
        }
        for name, (inventory, kind, message) in cases.items():
            with self.subTest(case=name):
                result = self.run_assets(inventory)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn(kind, result.stdout)
                self.assertIn(message, result.stdout)

    def test_symlinked_assets_are_rejected_without_reading_outside(self):
        def link(folder):
            outside = folder.parent / "outside.pdf"
            outside.write_bytes(PDF)
            try:
                os.symlink(outside, folder / "assets" / "01-link.pdf")
            except (OSError, NotImplementedError) as exc:
                raise unittest.SkipTest(f"cannot create symlinks here: {exc}")
        record = asset_record(path="assets/01-link.pdf")
        result = self.run_assets([asset_record(), record], setup=link)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("goes through a symlink", result.stdout)
        self.assertNotIn("[asset-hash]", result.stdout)


def compare(baseline):
    """Report observed CLI findings; baseline need not implement the new flag."""
    for label, checker in (("baseline", baseline), ("candidate", CHECKER)):
        incomplete = [run_check(note, checker=checker) for note in INCOMPLETE.values()]
        valid = [run_check(note, checker=checker) for note in VALID.values()]
        if any(r.returncode != 0 for r in incomplete + valid):
            raise RuntimeError(f"{label}: default-mode CLI failed; comparison is not valid")
        print(f"{label}: detected {sum(map(has_dimension_finding, incomplete))}/{len(incomplete)} "
              f"incomplete; findings on {sum(map(has_dimension_finding, valid))}/{len(valid)} valid; "
              "all default exits 0")
    strict = [run_check(note, strict=True) for note in INCOMPLETE.values()]
    print(f"candidate strict: {sum(r.returncode == 1 and has_dimension_finding(r) for r in strict)}"
          f"/{len(strict)} incomplete cases exit 1 with dimension diagnostics")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--compare":
        compare(Path(sys.argv[2]).resolve())
    else:
        unittest.main()
