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
python3 evals/run_triggers.py --limit 2
python3 evals/check_triggers.py
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

The following commands are prepared for later; **neither was run for the recorded smoke check**.
They spend subscription quota. A complete sweep starts up to 60 new sessions, including
the two smoke queries again. The baseline starts up to two more.

```bash
python3 evals/run_triggers.py --limit 60 --workers 1 --output evals/results/triggers-full.csv
python3 evals/run_baseline.py --run --output evals/results/baseline-pair.md
```

Score a full result explicitly with `python3 evals/check_triggers.py evals/results/triggers-full.csv`.
The default checker selects the most recently modified `triggers-*.csv`.
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
- Exit **0**: all 60 unique corpus rows, no session errors, recall >=90%, false rate <=20%.
  Exit **1**: an observed routing threshold fails, even on a partial sample.
  Exit **2**: incomplete or invalid evidence without an observed threshold failure.

The checker validates row IDs and corpus text, rejecting duplicate, unknown or mismatched
rows. It prints failing queries for later description review. A partial sample cannot
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
constraints, not an operating-system sandbox. No baseline session was run in this change.

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

## Scope limits

`GUIDE.html` was absent from this checkout. The supplied card's testing criteria were used.
`crit-response-plan` is outside the published repository and was excluded. No private
skill files were copied into this repository, and no SKILL.md or description was edited.
