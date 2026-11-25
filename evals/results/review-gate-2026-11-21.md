# PDF review-completion gate — 2026-11-21

## Mechanism and scope

Inspired by the supplied PosterMELD description's separation of programmatic and visual
acceptance: https://huggingface.co/papers/2608.02218. No source code, published performance
numbers, external evaluator, or model calls are used here.

The existing `skills/sheet-review/scripts/pdf_preflight.py` now constructs an artifact-bound
review contract and validates persisted tile records. `--require-review` returns 0 complete,
1 fail, or 2 incomplete. Without it, the old automated-only 0/1 exit behavior remains.
The helper is standard-library-only; the existing PDF/render dependencies are unchanged.

## Paired offline measurement

Baseline: `pdf_preflight.py` from `origin/main` at `cfe9215`. Candidate: this proposal.
Platform: Windows 11, Python 3.13.14; already-installed preflight dependencies.
Input: committed `evals/fixtures/sheet-review.pdf`, plus a byte-changed copy for the stale
artifact case. No private sheet or outside data was read. The test drives the **real CLI**
for both versions, with the same PDF and check/render options. Only the candidate receives
`--require-review --review ...`, because the baseline has no persisted review interface.

```bash
# Save the baseline under a fresh scratch directory in this checkout first.
python evals/tests/test_review_gate.py --baseline <scratch>/pdf_preflight.py -v
```

| Observation | Baseline automated exit | Candidate strict exit |
|---|---:|---:|
| Invalid-completion cases rejected | 1/26 (3.8%) | 26/26 (100%) |
| Fully covered, hash-matched clean control accepted | 1/1 | 1/1 |
| Findings match between versions | Identical in all 27 pairs | Identical in all 27 pairs |
| Original fixture findings | 0 FAIL, 2 WARN | 0 FAIL, 2 WARN |

The 26 negative cases cover missing, duplicate and unknown tile IDs; wrong artifact and
contract hashes; partial/duplicate/unknown review pages; empty/pending/invalid tile records;
issue records without evidence; open issues (including issues hidden in a clean record);
undocumented resolution; malformed record types; invalid issue status; changed PDF bytes,
render settings, check settings, palette, comparison input and tile inventory; freshly bound
partial-page and no-tile runs; and an automated page-size FAIL with all-clean visual entries.
Only the automated FAIL was rejected by the old automated-only exit path.

Additional tests cover invalid JSON/schema shapes, every check/render option through the
CLI, equivalent explicit/default options, changed comparison-PDF bytes at the same path,
resolved issues, preservation of completed/stale/malformed reviews, output-path collisions,
invalid tile geometry and an empty-document inventory. The focused run passed **10 tests**
in 48.239 seconds, including the paired measurement. At default 150 DPI a separate strict
smoke run correctly returned 2 incomplete with 8 pending tiles and the same two warnings:
`hairline-strokes` and `small-text`.

This is a **completion-protocol** measurement, not proof that visual reviews are accurate
or that these sheets are print-ready. Clean/issue entries are synthetic test inputs; the
paired tests use 9 DPI overviews and 12 DPI tiles for speed. The gate cannot prove a person
actually inspected the images. The earlier November resource-use baseline is not a quality
baseline and is not reused as one here.

## Repository checks and limitations

- `python evals/make_fixture.py --check`: PASS (2 pages, 11 × 8.5 in, one hairline and one
  5 pt text span).
- `python skills/sheet-review/tests/seeded_eval.py <synthetic-36x24.pdf> --work <scratch>
  --palette '#000000,#FFFFFF'`: **5/5 detected**. The source was a newly generated blank
  36 × 24 sheet so all five seeded defects fit on-page. This is not a rerun on the private
  real sheet referenced by SKILL.md, which is unavailable.
- `python -m unittest discover -s evals/tests -v`: **66 tests; 4 failures, 4 errors**.
  All 10 new tests passed. An untouched archive of `origin/main` was tested with the same
  interpreter: **56 tests; the identical 4 failures and 4 errors**. Existing Windows issues:
  - `test_interrupt_stops_the_session_before_propagating`, `test_timeout_kills_process_group`:
    `AttributeError: module 'os' has no attribute 'killpg'`.
  - `test_first_skill_and_loaded_source_proof`: `AssertionError: 1 != 0` (path matching).
  - `test_prompt_frontmatter_uses_only_documented_keys`, `test_smoke_tag_selects_six_cases`:
    mixed Windows/POSIX path separators produce `KeyError`.
  - `test_check_detects_stale_and_unknown_files`, `test_committed_suite_matches_the_builder`,
    `test_every_case_has_graders_of_documented_types`: path-dependent suite assertions fail.
  These unrelated harness issues were not changed to make the proposal's tests look green.
- No packages installed, no production configuration changed, no paid/model evaluations run.

The measured gain justifies a reviewable proposal for the completion gate, not a claim of
improved visual inspection quality or the source paper's poster-generation capability.
