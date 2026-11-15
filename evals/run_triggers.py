#!/usr/bin/env python3
"""Evaluate skill routing; defaults to two sessions, never retries a session."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
from pathlib import Path
import shlex
import sys

from eval_common import ROOT, SKILLS, check_cli, command, run_session, session_workspace

INPUT = ROOT / "evals/triggers.csv"


def load_rows(path=INPUT):
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["skill", "query", "should_trigger", "note"]:
            raise ValueError("Input columns must be skill,query,should_trigger,note.")
        rows = list(reader)
    seen = set()
    for i, row in enumerate(rows, 1):
        if (None in row or any(v is None for v in row.values()) or row["skill"] not in SKILLS
                or row["should_trigger"] not in {"0", "1"} or not row["query"].strip()):
            raise ValueError(f"Invalid input row {i}.")
        key = (row["skill"], row["query"])
        if key in seen:
            raise ValueError(f"Duplicate input row {i}.")
        seen.add(key)
        row["row_id"] = i
    for skill in SKILLS:
        group = [r for r in rows if r["skill"] == skill]
        if len(group) != 15 or sum(r["should_trigger"] == "1" for r in group) != 10:
            raise ValueError(f"{skill} needs 10 positive and 5 negative rows.")
    return rows


def evaluate(row, version):
    with session_workspace() as (work, hashes):
        observation = run_session(command(work, row["query"]), work)
        return {**row, "cli_version": version, "skill_sha256": hashes[row["skill"]], **observation}


def execute_rows(rows, evaluate_one, workers=1):
    """The first two run serially so quota/no-Skill failures cannot fan out."""
    results = []
    for row in rows[:2]:
        result = evaluate_one(row)
        results.append(result)
        yield result
        if result["status"] != "ok" or result["hook_events"]:
            return
    if len(results) == 2 and not any(r["skill_calls"] for r in results):
        return
    # Batches bound in-flight work to <=3. No new batch after any observed error.
    for start in range(2, len(rows), workers):
        batch = rows[start:start + workers]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(evaluate_one, row) for row in batch]
            results = [future.result() for future in as_completed(futures)]
        for result in sorted(results, key=lambda r: int(r["row_id"])):
            yield result
        if any(r["status"] != "ok" or r["hook_events"] for r in results):
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--limit", type=int, default=2, help="maximum sessions (default: 2; full suite: 60)")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--dry-run", action="store_true", help="print commands; no CLI sessions or result files")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 60:
        parser.error("--limit must be between 1 and 60")
    try:
        rows = load_rows(args.input)[:args.limit]
        if args.dry_run:
            # Stable illustrative paths, no temp files or personal settings reads.
            for row in rows:
                print(f"row {row['row_id']} cwd=/tmp/arch-skill-eval-<fresh>")
                print(shlex.join(command(Path("/tmp/arch-skill-eval-<fresh>"), row["query"])))
            print(f"DRY RUN: {len(rows)} commands; 0 sessions; 0 result rows written")
            return 0
        output = args.output or ROOT / "evals/results" / f"triggers-{datetime.now(timezone.utc):%Y-%m-%d}.csv"
        if output.exists():
            raise ValueError("Result file exists; choose a new --output to preserve evidence.")
        version = check_cli()
        output.parent.mkdir(parents=True, exist_ok=True)
        count, errors, hook_events, skill_calls = 0, 0, 0, 0
        # Open exclusively: an interrupted run preserves every completed observation.
        with output.open("x", newline="") as stream:
            writer = None
            for result in execute_rows(rows, lambda row: evaluate(row, version), args.workers):
                if writer is None:
                    writer = csv.DictWriter(stream, fieldnames=list(result), lineterminator="\n")
                    writer.writeheader()
                writer.writerow(result)
                stream.flush()
                count += 1
                errors += result["status"] != "ok"
                hook_events += result["hook_events"]
                skill_calls += result["skill_calls"]
                print(f"row {result['row_id']}: {result['status']} first_skill={result['first_skill'] or '(none)'} "
                      f"repo_loaded={result['repository_skill_loaded']} hook_events={result['hook_events']}", flush=True)
        print(f"Recorded {count}/{len(rows)} requested rows; session errors={errors}")
        stopped = count < len(rows) or hook_events > 0 or (count == 2 and skill_calls == 0)
        if stopped:
            print("STOP: session error, hook activity, or no Skill calls in the first two attempts.")
        return 2 if errors or stopped else 0
    except (ValueError, OSError) as exc:
        # Exception messages can contain private paths; report only controlled errors.
        if isinstance(exc, ValueError):
            print(f"ERROR: {exc}", file=sys.stderr)
        else:
            print(f"ERROR: {type(exc).__name__}; check CLI availability and file permissions.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
