Command: `claude plugin eval . --tag smoke --runs 1 --model haiku --judge-model haiku --max-cost-usd 1.5 --trust-plugin --no-publish --output-dir <scratch>`

Claude Code 2.1.325; agent model haiku, judge haiku; ablation with-without; 6 cases; overall with-arm score 1.00; mean Δ 0.61; cases passed 6/6; estimated list-price cost $0.0245; 93 s; partial: False.

| Case | With | Without | Δ | Graders, with-arm first run | Turns with/without | Cost USD |
|---|---|---|---|---|---|---|
| bambu-print-recipes-content-railing-supports | 1.00 | 0.00 | 1.00 | skill-fired pass (indicator), verdict pass, xy-distance pass | 3/1 | 0.0050 |
| bambu-print-recipes-neg-r48 | 1.00 | 1.00 | 0.00 | skill-not-fired pass | 1/1 | 0.0030 |
| bambu-print-recipes-pos-r04 | 1.00 | 0.00 | 1.00 | skill-fired pass | 3/1 | 0.0043 |
| sheet-review-content-hairline-small-text | 1.00 | 0.33 | 0.67 | hairline-limit pass, skill-fired fail (indicator), text-limit pass, verdict pass | 1/1 | 0.0058 |
| sheet-review-neg-r45 | 1.00 | 1.00 | 0.00 | skill-not-fired pass; run error: exit 1: Reached maximum number of turns (4) | 5/5 | 0.0039 |
| sheet-review-pos-r01 | 1.00 | 0.00 | 1.00 | skill-fired pass; run error: exit 1: Reached maximum number of turns (4) | 5/4 | 0.0043 |

## Notes

- Six cases were executed, one run per arm (with plugin, no-plugin baseline): 12 agent runs on Haiku plus 12 Haiku
  judge votes (2 cases with an `llm` grader x 2 arms x 3 votes). The other 30 cases in `evals/plugin-eval/` were not run. One run per arm is noisy; these scores show
  that the suite loads, grades and records, not how well the skills perform.
- The tool reports cost only, as a list-price estimate in USD; `aggregate-result.json` has no token counts.
- `sheet-review-content-hairline-small-text` passed in the with-arm although the skill was not called (the Skill
  grader is a non-scored indicator in a two-arm run). Haiku answered from its own knowledge in that run; the
  no-plugin run of the same prompt failed two of three graders. Re-run with `--runs 3` before reading anything into it.
- Two trigger runs hit the 4-turn cap that the suite used at the time (recorded as a run error, still graded).
  Trigger cases now allow 8 turns; that change has not been re-run.
- `plugin-eval-2026-11-15.json` is the tool's `aggregate-result.json` with prompts, replies, judge evidence,
  grader explanations, trace paths and local paths removed (`python3 evals/plugin_eval.py summarize`).
