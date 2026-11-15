# Trigger evaluation verification

Branch: `tac376/s12-12-trigger-evals`. Claude Code: `2.1.325` (the card named `2.1.280`).
Exactly two model sessions were started. Both completed; neither reported a usage-limit error.
No further model sessions or baseline comparison were run.

## Measured routing

| Skill | Observed rows | Positive hits | Recall on observed positives | Negative rows | False-trigger rate |
|---|---:|---:|---:|---:|---:|
| sheet-review | 1/15 | 1/1 | 100% | 0/5 | n/a |
| sun-study | 1/15 | 1/1 | 100% | 0/5 | n/a |
| physical-model-prep | 0/15 | n/a | n/a | 0/5 | n/a |
| bambu-print-recipes | 0/15 | n/a | n/a | 0/5 | n/a |

Coverage is **2/60**, not a full-suite pass. No competing first skill or failing query
was observed. Proposed description changes: **none supported by this sample**.
No SKILL.md was edited. Do not infer routing quality for the 58 unmeasured queries.

| Smoke query | First Skill input | Staged body verified | Failed tool calls | Total tokens | Result duration ms |
|---|---|---:|---:|---:|---:|
| check this exported presentation sheet pdf before i print | arch-eval:sheet-review | yes | 0 | 52,218 | 21,163 |
| how many direct sun hours does this courtyard get on dec 21 | arch-eval:sun-study | yes | 0 | 52,583 | 22,271 |

Token totals include cache reads and cache creation. Each stream contained `system`,
`assistant`, `user`, `rate_limit_event`, and `result` events, with zero malformed JSON
lines. A `rate_limit_event` being present is not itself a usage-limit failure.

## Skill source and hook observations

The harness copied the four skill folders from this checkout into a temporary
`arch-eval` plugin and checked each SKILL.md hash. Both observed first Skill calls
used the plugin namespace; their successful tool results and emitted staged base
directories confirmed repository skill-body loading. Source hashes are in the CSV.

All four same-named personal skills were present locally. Per-session overrides hid
their unqualified names; plugin-qualified repository names remained available. No
personal skill files were edited. Each init advertised 177 catalog entries: all four
repository targets plus 173 other entries. The saved aggregates cannot distinguish
personal entries from built-ins; a separate personal-body invocation was not attempted.

The chosen configuration is `--setting-sources user` plus a session-only
`disableAllHooks: true` override, disabled user-configured plugins, and an explicit
empty MCP config. Settings-source selection alone does not suppress user hooks.
Configured hook categories included vault context, handoff and dream. **Zero hook
events were observed in each smoke stream.** Managed policy can override local settings;
future observed hook activity stops further scheduling. See [runner documentation](../README.md).

## Commands and outcomes

| Command | Outcome |
|---|---|
| `python3 -m unittest discover -s evals/tests -v` | 30 passed, 0 failed; no live sessions |
| `python3 evals/run_triggers.py --limit 4 --dry-run` | 4 commands printed, 0 sessions, 0 result rows written |
| `python3 evals/run_triggers.py --limit 2` | 2 completed sessions, 0 session errors; 2 CSV rows |
| `python3 evals/check_triggers.py` | exit 2: incomplete; 2/60 observations, no observed routing failure |
| `python3 evals/make_fixture.py --check` | 2 pages, 1 hairline, 1 small-text span verified |
| `python3 skills/sheet-review/scripts/pdf_preflight.py evals/fixtures/sheet-review.pdf --out /tmp/arch-eval-fixture-preflight --expect-size 11x8.5 --no-tiles` | exit 0; 0 failures, 2 expected warnings |
| `python3 evals/run_baseline.py --dry-run` | 2 commands printed, 0 sessions; baseline unmeasured |
| `git diff --cached --check` | no whitespace errors after normalizing CSV line endings to LF |

Both fixture pages were rendered and visually inspected. The normal text and graphics
were unclipped; the hairline on page 1 and 5 pt text on page 2 are intentional defects.
The local preflight reported `hairline-strokes` on page 1 and `small-text` on page 2.
This local script check is separate from the deferred model baseline.

After the live smoke check, offline tests covered two additional edge cases: repeated
stream blocks count a Skill call once, and two no-Skill smoke results return incomplete
even when the requested limit is two. No additional live sessions were used to retest
those branches. The measured streams each contained only one Skill call.

## Deferred work

- Full sweep: `python3 evals/run_triggers.py --limit 60 --workers 1 --output evals/results/triggers-full.csv`.
- Paired baseline: `python3 evals/run_baseline.py --run --output evals/results/baseline-pair.md`.
- Functional agent-output comparison and negative-trigger rates remain unmeasured.
- `GUIDE.html` was absent from this checkout. No private or other-checkout substitute was read.
- No push, pull request, merge, tag, release or publication was performed.

The [baseline report](baseline-2026-11-15.md) explicitly marks every baseline metric as
not measured. The smoke CSV is `triggers-2026-11-15.csv`. No synthetic rows were added
to make it appear complete.

## Questions for follow-up

Where is the intended public `GUIDE.html` source? It can be reviewed when supplied;
the supplied card's testing criteria were sufficient to build the harness.
