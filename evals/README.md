# Architecture skill trigger evaluations

The corpus has 60 short, lowercase queries: 10 positive and 5 negative cases each for
`sheet-review`, `sun-study`, `physical-model-prep`, and `bambu-print-recipes`.
Cases are interleaved by skill. The first two are positive smoke cases for different skills.
No skill descriptions are edited by these tools.

## Commands

Run from the repository root, with Python 3.10+ and a Claude Code subscription login.
The trigger runner uses only the Python standard library. Fixture generation and the
PDF preflight use PyMuPDF from `requirements-arch-tools.txt`.

```bash
python3 -m unittest discover -s evals/tests -v
python3 evals/run_triggers.py --limit 4 --dry-run
# Fresh output directory for this invocation.
# Only the live trigger run spends subscription quota; check_triggers.py scores the CSV locally.
eval_run_dir=$(mktemp -d "${TMPDIR:-/tmp}/arch-evals.XXXXXX")
python3 evals/run_triggers.py --limit 2 --output "$eval_run_dir/smoke.csv"
python3 evals/check_triggers.py "$eval_run_dir/smoke.csv"  # expected INCOMPLETE for 2/60 rows
python3 evals/make_fixture.py --check
python3 evals/run_baseline.py --dry-run
```

The default trigger limit is **2**, the default worker count is **1**, and the baseline
defaults to a dry run. Dry runs do not start Claude, create sessions or write results.
`--workers 1|2|3` bounds concurrent sessions; the first two always run serially.
Each session has a 120-second wall timeout, including startup, and is never retried.
The process group is killed on timeout. An error, usage-limit response or observed hook
event stops further scheduling. With concurrent batches, already-started sessions may
finish. Two opening attempts with no Skill call also stop the run.

The following commands were not part of the recorded smoke check; both were run later (see `results/sweep-2026-11-15.md`).
They spend subscription quota. A complete sweep starts up to 60 new sessions, including
the two smoke queries again. The baseline starts up to two more.

```bash
eval_run_dir=$(mktemp -d "${TMPDIR:-/tmp}/arch-evals.XXXXXX")
python3 evals/run_triggers.py --limit 60 --workers 1 --output "$eval_run_dir/triggers-full.csv"
python3 evals/check_triggers.py "$eval_run_dir/triggers-full.csv"
python3 evals/run_baseline.py --run --output "$eval_run_dir/baseline-pair.md"
```

The checker requires an explicit result CSV; checkout modification times do not select evidence.
Committed `evals/results/triggers-full.csv` and `evals/results/baseline-pair.md` are historical evidence,
not output destinations for a new run. To score that historical CSV, use
`python3 evals/check_triggers.py evals/results/triggers-full.csv`.
Results default to UTC-dated names. Existing result files are never overwritten; pass
a new `--output` for another run. The session cap is per invocation, not a lifetime budget.

## Which skill source is tested

Every session starts in a fresh temporary directory outside any git repository. The
harness copies the **four skill directories from this checkout** into a temporary plugin:

```text
<temporary-directory>/plugin/
  .claude-plugin/plugin.json       # name: arch-eval
  skills/<skill-name>/SKILL.md      # byte-for-byte repository copy
  skills/<skill-name>/scripts/...  # supporting files, where present
```

`--plugin-dir` loads that plugin, giving names such as `arch-eval:sheet-review`.
Each copied SKILL.md is checked against its repository SHA-256 before launch. The target
hash is recorded in the CSV. A positive hit requires the first Skill call to name the
expected plugin skill, a successful tool result, and the staged skill base directory
in the emitted stream. An unqualified `sheet-review` call is a different source and
cannot count as a repository hit. The tool input's skill name is recorded in `first_skill`.
`all_skills` is diagnostic only: a later correct call does not repair a wrong first call.

Personal skills stay enabled through `--setting-sources user`. The per-session
`--settings` file sets `skillOverrides` to `off` for the four unqualified target names.
This prevents same-named personal copies from competing with the plugin copies, without
changing anything under the personal skills directory. Plugin skills are not affected
by those overrides. Other personal skills and built-ins can still compete. Names from
outside this public repository are recorded as `[other-skill]`.
See the official [skill visibility documentation](https://code.claude.com/docs/en/skills#override-skill-visibility-from-settings).

## Settings, hooks and authentication

`--setting-sources user` alone does **not** suppress user hooks. The session settings
also set `disableAllHooks: true` and disable user-configured installed plugins for that
run; the explicit evaluation plugin remains loaded. Project and local settings are
excluded. The CLI uses `--strict-mcp-config` with `{"mcpServers": {}}`, `--no-chrome`,
`--no-session-persistence`, and `--include-hook-events`. Trigger sessions expose only
the `Skill` tool. No GUI or fabrication tools are available.

`--bare` is unsuitable here: this installed CLI's help says it skips subscription
OAuth/keychain authentication. The harness instead checks for a first-party `claude.ai`
login without printing account details, strips API/provider auth environment variables,
and refuses user settings that select an API helper or provider credentials. It uses
the configured Claude model; it does not choose an API key or fall back to another provider.

User-level CLAUDE.md and other skill metadata can still contribute context and token
cost. These are routing measurements in that environment, not a clean-room four-skill
benchmark. The smoke init events advertised 177 catalog entries, including all four
repository plugin skills and 173 other entries. That demonstrates other metadata stayed
available; the saved aggregates do not distinguish personal entries from built-ins,
and no personal skill body was invoked in the smoke check.

The locally configured hook categories included vault context, handoff and dream.
Neither smoke stream emitted a hook event. This is evidence for these two runs, not
a claim about every installation. Managed hooks may remain active despite a session
override; if any hook event appears, the harness stops scheduling more sessions.
See the official [hook setting reference](https://code.claude.com/docs/en/settings-reference#disableallhooks)
and [CLI flags](https://code.claude.com/docs/en/cli-reference).

Raw stdout, stderr, assistant text, hook commands, account identifiers and temporary
paths are not written into public results. Only aggregate metrics and public skill names
are retained. This intentionally limits diagnosis of redacted competing skills.

## Scoring

- Recall = successful first-call repository hits / usable positive cases for that skill.
- False-trigger rate = first-call attempts at that repository skill / usable negative cases.
  A failed target tool call still counts as a false trigger on a negative case.
- Other first skills are printed separately. A different skill can be appropriate on a
  negative query; it is not a false trigger of the target skill.
- Session errors and unexpected hook activity are excluded from rates and counted as errors.
  Missing observations produce `n/a`, never zero. Coverage is printed for each skill.
- Exit **0**: valid source lineage, all 60 unique corpus rows, no session errors,
  recall >=90%, false rate <=20%.
  Exit **1**: an observed routing threshold fails, even on a partial sample, after validation.
  Exit **2**: invalid evidence, or incomplete evidence without an observed threshold failure.

The checker validates row IDs and corpus text, rejecting duplicate, unknown or mismatched
rows. Every result row (including session errors) must have a 64-digit hexadecimal
`skill_sha256` and a nonblank `cli_version`. A result set must contain exactly one CLI
version and one revision per observed skill. Hexadecimal letter case is ignored; CLI
versions must match exactly. Missing columns, malformed hashes and mixed revisions or
versions are invalid evidence, not routing failures.

By default, each observed hash must match **this checkout's** `skills/<name>/SKILL.md`,
using the same SHA-256 helper as the runner. Missing/unreadable current skill files or
changed bytes prevent a current-source PASS. Re-run the evaluation after changing a
skill, or explicitly score a coherent older result:

```bash
python3 evals/check_triggers.py evals/results/triggers-full-after-fix.csv --historical
```

`--historical` skips only the comparison with current skill bytes. It still validates
lineage metadata, corpus identity, coverage, session errors and routing thresholds.
Every verdict (including validation errors) is prefixed `HISTORICAL`; a historical PASS
is not evidence for the current source. Neither mode starts Claude or requires the
recorded CLI version to be installed. Hashes cover target SKILL.md bytes only, not scripts,
other skill descriptions or the full runtime environment; CSV metadata is not a signed attestation.

The checker prints failing queries for later description review. A partial sample cannot
establish full-suite recall or false-trigger performance. A source-loading failure should
be investigated before attributing it to description wording.

## Fixture and baseline

`fixtures/sheet-review.pdf` is synthetic, with two 11 x 8.5 inch pages, embedded fonts,
a single 0.05 pt stroke on page 1, and one 5 pt text box on page 2. Rebuild it with
`python3 evals/make_fixture.py`. The seeded defects are intentional.

The paired baseline uses the same prompt, fixture and PDF inspection scripts in fresh
temporary directories. Only its second command adds `--disable-slash-commands`.
Both commands can read files and execute `python3` shell commands; neither has app/MCP
tools. The prompt explicitly says `fixture PDF only; do not open InDesign or any app`,
and prohibits reading SKILL.md directly. The shell restriction and prompt are task
constraints, not an operating-system sandbox. `run_baseline.py --timeout` sets the per-session limit (default 600 seconds).

Baseline messages count the submitted prompt plus unique assistant messages and emitted
user/tool-result messages. Failed calls count unique `tool_result` IDs marked `is_error`.
Total tokens include input, output, cache-creation input and cache-read input from the
result event. Missing usage remains unknown. Token totals are workload counts, not cost
estimates. Duration is recorded from the result event; the trigger CSV also records wall time.
The baseline report checks whether the repository skill loaded in the enabled condition
and whether no skill was called in the disabled condition. It records resource use only;
these metrics alone cannot demonstrate better task quality.

`results/baseline-2026-11-15.md` records a deferred comparison, not measured results.
`results/verification-2026-11-15.md` records the smoke evidence and remaining checks.
`results/sweep-2026-11-15.md` records the full sweep, the description change it led to, and one baseline pair.

## Offline PDF review-completion gate

`python3 -m unittest discover -s evals/tests -v` also exercises the real PDF preflight
CLI against the committed two-page fixture. The review-gate tests need the preflight's
existing dependencies (PyMuPDF, numpy, Pillow and scipy); they make no model/network calls.
They check artifact/settings binding, exact tile and page coverage, persisted review
preservation, open issues, and non-waivable automated FAILs. Temporary outputs stay in
this checkout and are removed after the tests. A focused run is:

```bash
python3 evals/tests/test_review_gate.py -v
```

For a paired baseline, save `pdf_preflight.py` from the revision under comparison into
a scratch directory in this checkout, then run:

```bash
python3 evals/tests/test_review_gate.py --baseline <scratch>/pdf_preflight.py -v
```

The baseline runs the same fixture/PDF variants and check/render options without the new
review flags. Its actual automated-only exit code is compared with the candidate's strict
exit code; findings must remain identical for every pair. This measures invalid-completion
rejection, **not visual review quality**: clean/issue entries are synthetic test inputs,
and low DPI keeps protocol tests fast. See
[`results/review-gate-2026-11-21.md`](results/review-gate-2026-11-21.md) for measured results
and the existing Windows failures in the broader suite.

## `claude plugin eval` suite

`evals/plugin-eval/` holds a suite in Claude Code's own
[plugin eval format](https://code.claude.com/docs/en/plugin-evals) for `sheet-review` and `bambu-print-recipes`:
the 30 `triggers.csv` rows for those skills (a `tool_used: Skill` grader; negatives require zero calls in both arms)
and six content cases graded with `regex` and `llm` graders. `.claude-plugin/plugin.json` makes the repository a plugin
named `arch-skills` and points `experimental.evals` at that directory. It does not change the symlink install above.
Each run is isolated by the tool: no personal settings, skills, hooks, CLAUDE.md or MCP servers load, unlike the
trigger runner. Case files are generated; edit `plugin_eval.py`, not the Markdown:

```bash
python3 evals/plugin_eval.py build      # rewrite evals/plugin-eval/ from triggers.csv + CONTENT
python3 evals/plugin_eval.py check      # exit 1 if the committed suite is out of date
claude plugin eval . --tag smoke --runs 1 --model haiku --judge-model haiku \
  --max-cost-usd 1.5 --trust-plugin --no-publish --output-dir <scratch dir>
python3 evals/plugin_eval.py summarize <scratch dir>/aggregate-result.json \
  --json-out evals/results/plugin-eval-<date>.json --md-out evals/results/plugin-eval-<date>.md
```

The `smoke` tag selects six cases. Without `--tag` the command runs all 36 cases, by default three runs each in two
arms (216 agent runs) plus judge calls: that is a sweep, and it spends quota. The judge defaults to Haiku; the agent
model defaults to the configured one. The tool's raw `aggregate-result.json` contains prompts, replies and local
paths, so only the summarized JSON is committed. See `results/plugin-eval-2026-11-15.md`.

## SkillEvaluator static checks

[NVIDIA SkillEvaluator](https://github.com/NVIDIA/SkillEvaluator) (Apache-2.0, Python 3.12+) gives each skill an
independent quality score. Install it in a throwaway virtual environment, never globally. Keyless Tier 1, without the
SkillSpector security scan (it downloads a scanner) or the dependency audit; the PII check uses a local `gitleaks`:

```bash
python3.13 -m venv /tmp/se && /tmp/se/bin/pip install "skillevaluator[tier2]"
for s in skills/*/; do /tmp/se/bin/skillevaluator tier1 "$s" --no-llm \
  --checks schema,version,pii,license,code-integrity,unicode,quality,lint -r json -o "/tmp/se-out/$(basename "$s")"; done
# overlap between skills, with local Ollama embeddings (no external calls):
SKILL_EVAL_EMBEDDING_PROVIDER=openai-compatible SKILL_EVAL_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1 \
SKILL_EVAL_EMBEDDING_MODEL=nomic-embed-text SKILL_EVAL_EMBEDDING_API_KEY=local-no-key \
  /tmp/se/bin/skillevaluator similarity-check skills -r json -o /tmp/se-sim
python3 evals/summarize_skillevaluator.py --tier1 /tmp/se-out/*/skillevaluator-tier1.json \
  --similarity descriptions=/tmp/se-sim/skillevaluator-similarity.json \
  --json-out evals/results/skillevaluator-<date>.json --md-out evals/results/skillevaluator-<date>.md
```

Tier 2 chat checks, the rubric and Tier 3 live runs need a model provider and were not run. See
`results/skillevaluator-2026-11-15.md`.

## Scope limits

`GUIDE.html` was absent from this checkout. The supplied card's testing criteria were used.
`crit-response-plan` is outside the published repository and was excluded. No private
skill files were copied into this repository, and no SKILL.md or description was edited.
