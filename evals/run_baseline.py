#!/usr/bin/env python3
"""Run one paired sheet-review comparison only with --run; default is a dry run."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shlex
import shutil
import sys

from eval_common import ROOT, check_cli, command, run_session, session_workspace, sha256

PROMPT = (
    "preflight fixture.pdf before plotting at 11 x 8.5 inches. "
    "fixture PDF only; do not open InDesign or any app. "
    "Check both pages for page size, fonts, small text and hairlines. "
    "Report the issue locations and separate script evidence, visual observations, and not checked. "
    "Work only in this temporary directory. Use python3 for any shell work. "
    "The same PDF inspection scripts are available to both sessions in pdf-tools/; "
    "you may use them or write your own Python inspection. Do not read any SKILL.md directly."
)


def render_report(records, version, fixture_hash):
    lines = ["# Sheet-review baseline", "", f"CLI: {version}", f"Fixture SHA-256: `{fixture_hash}`", "",
             "| Condition | Status | Messages | Failed tool calls | Total tokens | Duration ms | First skill |",
             "|---|---|---:|---:|---:|---:|---|"]
    for label in ("with skills", "without skills"):
        r = records.get(label)
        if r is None:
            lines.append(f"| {label} | not run | n/a | n/a | n/a | n/a | n/a |")
        else:
            lines.append(f"| {label} | {r['status']} | {r['messages']} | {r['failed_tool_calls']} | "
                         f"{r['total_tokens']} | {r['duration_ms']} | {r['first_skill'] or '(none)'} |")
    lines += ["", "Messages = submitted prompt + unique assistant messages + emitted user/tool-result messages.",
              "Total tokens = input + output + cache creation input + cache read input, from the result event.",
              "Failed tool calls count unique tool_result IDs with is_error=true; session errors are separate.",
              "Both conditions receive identical prompts, fixture bytes and PDF scripts. Only the second adds",
              "--disable-slash-commands. No app or MCP tools are available. Shell permission is limited to python3.",
              "This is a single pair, not a statistical result. Resource counts alone do not establish quality.", ""]
    if len(records) == 2:
        with_skill, without = records["with skills"], records["without skills"]
        valid = (with_skill["status"] == without["status"] == "ok"
                 and with_skill["first_skill"] == "arch-eval:sheet-review"
                 and with_skill["repository_skill_loaded"] == 1 and without["skill_calls"] == 0
                 and not with_skill["hook_events"] and not without["hook_events"])
        lines.append("Pair validity: " + ("valid routing; functional findings need review." if valid else "not established."))
    else:
        lines.append("Pair validity: incomplete; stopped before the second session.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="consume two subscription sessions")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.run:
        for disabled in (False, True):
            print(shlex.join(command(Path("/tmp/arch-baseline-<fresh>"), PROMPT, baseline=True, disabled=disabled)))
        print("DRY RUN: 2 commands; 0 sessions; no baseline measured")
        return 0
    try:
        fixture = ROOT / "evals/fixtures/sheet-review.pdf"
        output = args.output or ROOT / "evals/results" / f"baseline-{datetime.now(timezone.utc):%Y-%m-%d}.md"
        if output.exists():
            raise ValueError("Baseline report exists; choose a new --output to preserve evidence.")
        version = check_cli()
        records = {}
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as report:
            for disabled in (False, True):
                with session_workspace() as (work, _):
                    shutil.copyfile(fixture, work / "fixture.pdf")
                    shutil.copytree(ROOT / "skills/sheet-review/scripts", work / "pdf-tools",
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                    result = run_session(command(work, PROMPT, baseline=True, disabled=disabled), work)
                    label = "without skills" if disabled else "with skills"
                    records[label] = result
                    report.seek(0)
                    report.write(render_report(records, version, sha256(fixture)))
                    report.truncate()
                    report.flush()
                    print(f"{label}: {result['status']}", flush=True)
                    if result["status"] != "ok" or result["hook_events"]:
                        return 2
        valid = (records["with skills"]["repository_skill_loaded"] == 1
                 and records["with skills"]["first_skill"] == "arch-eval:sheet-review"
                 and records["without skills"]["skill_calls"] == 0)
        return 0 if valid else 2
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc if isinstance(exc, ValueError) else type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
