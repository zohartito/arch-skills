# Dimension provenance: offline baseline / candidate

Date: 2026-11-21. Host: Windows, Python 3.13.14. No packages installed, external
services called, or source documents downloaded for this evaluation.

## Mechanism and scope

The existing `skills/precedent-dossier/scripts/check_ledger.py` CLI now checks the
provenance of number + unit claims in Markdown, rather than treating any citation
as sufficient. Written/scaled claims need a source pinpoint and method marker;
scaled claims also need an explicit scale. Derived claims need a nonempty method
and ledgered inputs. Explicitly labelled published figures are reported values,
not measurements. Table rows may separate source and method into different cells.
Legacy ledger URLs remain citations. Default mode warns; `--strict-dimensions`
makes incomplete dimension provenance an error without promoting other warnings.

Pattern inspiration: https://github.com/AlpacaLabsLLC/skills-for-architects
No upstream code or benchmark numbers were copied. This implements the rules already
present in this repository's precedent-dossier skill.

## Reproduction

Run from the repository root; use an unused scratch directory inside the checkout:

```bash
mkdir dimension-baseline-tmp
git show cfe92150a3764795dc5ed64b9784631f8155f63a:skills/precedent-dossier/scripts/check_ledger.py > dimension-baseline-tmp/check_ledger.py
python -m unittest discover -s skills/precedent-dossier/tests -v
python skills/precedent-dossier/tests/test_check_ledger.py --compare dimension-baseline-tmp/check_ledger.py
```

The test harness invokes each actual CLI in a subprocess against the same generated
SOURCES.csv and Markdown fixtures. Fixtures live temporarily inside the checkout.
There are 60 labelled provenance cases: 29 deliberately incomplete and 31 valid.
Additional compatibility checks cover unknown IDs, malformed ledger URLs, JSON,
fenced examples, non-dimension text, unrelated warnings and actionable diagnostics.

## Observed comparison

| Measure | Baseline (`cfe9215`) | Candidate |
|---|---:|---:|
| Incomplete cases with dimension findings (default mode) | 4 / 29 | 29 / 29 |
| Valid controls with dimension findings (default mode) | 0 / 31 | 0 / 31 |
| Default-mode exit 0, all provenance cases | 60 / 60 | 60 / 60 |
| Incomplete cases exit 1 with dimension diagnostics, strict mode | unsupported | 29 / 29 |
| Valid controls exit 0 with zero warnings/errors, strict mode | unsupported | 31 / 31 |

The initial red test against the unchanged validator failed on 20 of the initial
24 incomplete cases. The final corpus adds timestamp/scale confusion, invalid
scales, empty derived methods and additional valid controls. Final provenance
unittest run: **10 test methods passed** (subtests exercise all labelled cases).

## Existing suites and limits

- `python -m unittest discover -s evals/tests -v`: **48 passed, 4 failures, 4 errors**,
  identical before and after the change. Windows lacks `os.killpg` (two errors);
  POSIX/path-separator assumptions account for the remaining failures/errors in
  source-loading and plugin-suite tests. These unrelated files were not changed.
- `python skills/rhino-safe-capture/tests/test_rhino_live_guard.py`: **12 passed**.
- `python -m pytest skills/sun-study/tests -q`: **3 passed, 7 failed**; all seven
  failures report `ModuleNotFoundError: No module named 'ladybug'`. No dependency
  installation was attempted.
- `git diff --check`: passed.

This is a deterministic synthetic regression corpus, not a claim about detection
rates on real research dossiers. The validator remains line-based: keep one claim
per line/row. It does not verify source contents, method correctness, authority,
unit conversions, or whether every calculation input was disclosed. Existing unit
recognition and citation-only JSON handling are unchanged. No live agent/model,
network research, or paid evaluation was run.
