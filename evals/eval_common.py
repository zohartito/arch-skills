"""Shared, quota-conscious Claude CLI support. No raw session text is persisted."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("sheet-review", "sun-study", "physical-model-prep", "bambu-print-recipes")
NAMESPACE = "arch-eval"
PUBLIC_SKILLS = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
LIMIT_PATTERN = re.compile(
    r"\b(?:usage|rate)[ _-]limit(?:s)?\b|\byou(?:'ve| have) hit your limit\b|"
    r"\bout of (?:usage|credits)\b|\binsufficient[ _-]quota\b", re.I
)
AUTH_ENV = {
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_FOUNDRY_API_KEY",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_skill(name):
    """Only repository skill names are eligible for public result files."""
    if name in PUBLIC_SKILLS or name in {f"{NAMESPACE}:{s}" for s in SKILLS}:
        return name
    return "[other-skill]" if name else ""


def environment():
    env = {k: v for k, v in os.environ.items() if k not in AUTH_ENV}
    env.update({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                "CLAUDE_CODE_DISABLE_WORKFLOWS": "1"})
    return env


def settings():
    # Read only configuration keys needed to prevent plugin startup and API auth.
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    path = config / "settings.json"
    user = json.loads(path.read_text()) if path.exists() else {}
    if user.get("apiKeyHelper") or AUTH_ENV.intersection(user.get("env", {})):
        raise ValueError("User settings configure API/provider authentication; subscription-only run refused.")
    return {
        "disableAllHooks": True,
        "autoMemoryEnabled": False,
        "remoteControlAtStartup": False,
        "enabledPlugins": {name: False for name in user.get("enabledPlugins", {})},
        # Personal skills remain discoverable, but these four cannot shadow the plugin.
        # Plugin skills are not affected by skillOverrides.
        "skillOverrides": {name: "off" for name in SKILLS},
    }


@contextmanager
def session_workspace():
    # No checkout, inherited project settings, or source-repository mutations.
    with tempfile.TemporaryDirectory(prefix="arch-skill-eval-") as folder:
        work = Path(folder).resolve()
        if any((p / ".git").exists() for p in (work, *work.parents)):
            raise ValueError("Temporary directory must be outside every git repository.")
        plugin = work / "plugin"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin/plugin.json").write_text(json.dumps({
            "name": NAMESPACE, "version": "1.0.0", "description": "Repository skill evaluation"
        }))
        hashes = {}
        for name in SKILLS:
            src = ROOT / "skills" / name
            dst = plugin / "skills" / name
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
            hashes[name] = sha256(src / "SKILL.md")
            if sha256(dst / "SKILL.md") != hashes[name]:
                raise ValueError("Staged skill hash mismatch.")
        (work / "empty.json").write_text('{"mcpServers": {}}\n')
        (work / "settings.json").write_text(json.dumps(settings()))
        yield work, hashes


def command(work, prompt, *, baseline=False, disabled=False):
    tools = "Skill,Read,Bash" if baseline else "Skill"
    allowed = ["Skill", "Read", "Bash(python3 *)"] if baseline else ["Skill"]
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--strict-mcp-config", "--mcp-config", str(work / "empty.json"),
           "--tools", tools, "--allowedTools", *allowed,
           "--setting-sources", "user", "--settings", str(work / "settings.json"),
           "--plugin-dir", str(work / "plugin"), "--include-hook-events", "--no-chrome",
           "--permission-mode", "dontAsk"]
    if disabled:
        cmd.append("--disable-slash-commands")
    return cmd


def check_cli():
    """Local CLI/auth checks do not start a model session or print account details."""
    help_text = subprocess.run(["claude", "--help"], capture_output=True, text=True, check=True).stdout
    for flag in ("--include-hook-events", "--plugin-dir", "--setting-sources", "--disable-slash-commands"):
        if flag not in help_text:
            raise ValueError(f"Installed Claude CLI lacks {flag}.")
    result = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True,
                            env=environment(), timeout=30)
    try:
        auth = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError("Could not verify subscription authentication.") from exc
    if result.returncode or auth.get("authMethod") != "claude.ai" or auth.get("apiProvider") != "firstParty":
        raise ValueError("A first-party Claude subscription login is required; no API fallback.")
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"\b\d+\.\d+\.\d+\b", version)
    return match.group() if match else "unknown"


def parse_stream(stdout, stderr="", *, work=None, returncode=0, timed_out=False, wall_ms=0):
    events, invalid = [], 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("not an object")
            events.append(event)
        except (ValueError, TypeError):
            invalid += 1
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    first, first_id, all_skills = "", None, []
    failed_ids, successful_ids, tool_ids, skill_ids, assistant_ids, user_ids = set(), set(), set(), set(), set(), set()
    hooks, types, catalog = [], set(), set()
    for i, event in enumerate(events):
        kind = event.get("type", "unknown")
        # Fixed categories: never persist arbitrary event text or hook commands.
        types.add(kind if kind in {"system", "assistant", "user", "result", "rate_limit_event", "stream_event"} else "other")
        if "hook" in event.get("subtype", "") or "hook" in kind:
            encoded = json.dumps(event).lower()
            hooks.append(next((n for n in ("vault", "handoff", "dream") if n in encoded), "other"))
        if kind == "system" and event.get("subtype") == "init":
            for key in ("skills", "slash_commands"):
                for skill in event.get(key, []):
                    if isinstance(skill, str):
                        catalog.add(skill)
                    elif isinstance(skill, dict) and isinstance(skill.get("name"), str):
                        catalog.add(skill["name"])
        message = event.get("message", {})
        if not isinstance(message, dict):
            continue
        if kind == "assistant":
            assistant_ids.add(message.get("id") or event.get("uuid") or str(i))
        elif kind == "user":
            user_ids.add(message.get("id") or event.get("uuid") or str(i))
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if kind == "assistant" and block.get("type") == "tool_use":
                tool_ids.add(block.get("id", str(i)))
                if block.get("name") == "Skill" and block.get("id", str(i)) not in skill_ids:
                    skill_ids.add(block.get("id", str(i)))
                    skill_input = block.get("input", {})
                    name = skill_input.get("skill", "") if isinstance(skill_input, dict) else ""
                    name = name if isinstance(name, str) else ""
                    all_skills.append(name)
                    if first_id is None:
                        first, first_id = name, block.get("id", str(i))
            if block.get("type") == "tool_result":
                target = failed_ids if block.get("is_error") else successful_ids
                target.add(block.get("tool_use_id", str(i)))
    usage = (result or {}).get("usage") or {}
    counts = {key: usage.get(key, "") for key in TOKEN_KEYS}
    total = sum(counts.values()) if all(isinstance(v, (int, float)) for v in counts.values()) else ""
    # Successful prose is evidence, not an error message. Prefer explicit error codes;
    # use narrow text matching only on failed results/errors or failed-process stderr.
    succeeded = result is not None and not result.get("is_error") and result.get("subtype") == "success" and not returncode
    errors = [e for e in events if e.get("type") == "error" or e.get("is_error") or e.get("error")
              or str(e.get("subtype", "")).startswith("error")]
    quota_codes = {"rate_limit", "rate_limit_error", "usage_limit", "insufficient_quota"}
    structured_limit = any(
        (e["error"].get("type") in quota_codes or e["error"].get("code") in quota_codes)
        if isinstance(e.get("error"), dict) else e.get("error") in quota_codes
        for e in errors)
    error_text = "\n".join(json.dumps(e) for e in errors)
    if returncode or result is None:
        error_text += "\n" + stderr
    limited = not succeeded and (structured_limit or bool(LIMIT_PATTERN.search(error_text)))
    if limited:
        status = "usage_limit"
    elif timed_out:
        status = "timeout"
    elif returncode:
        status = "process_error"
    elif result is None:
        status = "missing_result"
    elif result.get("is_error") or str(result.get("subtype", "")).startswith("error"):
        status = "session_error"
    elif invalid:
        status = "malformed_stream"
    else:
        status = "ok"
    repository_loaded = False
    if first.startswith(f"{NAMESPACE}:") and first.split(":", 1)[1] in SKILLS and work:
        name = first.split(":", 1)[1]
        base = str(work / "plugin/skills" / name)
        # Tool success plus the emitted skill base directory verifies the loaded body.
        repository_loaded = first_id in successful_ids and base in stdout and first_id not in failed_ids
    return {
        "status": status, "first_skill": public_skill(first),
        "all_skills": ";".join(dict.fromkeys(public_skill(s) for s in all_skills)),
        "repository_skill_loaded": int(repository_loaded), "skill_calls": len(all_skills),
        "tool_calls": len(tool_ids), "failed_tool_calls": len(failed_ids),
        "messages": 1 + len(assistant_ids) + len(user_ids),
        "assistant_messages": len(assistant_ids), "user_events": len(user_ids),
        **counts, "total_tokens": total, "duration_ms": (result or {}).get("duration_ms", ""),
        "duration_api_ms": (result or {}).get("duration_api_ms", ""), "wall_ms": wall_ms,
        "hook_events": len(hooks), "hook_categories": ";".join(sorted(set(hooks))),
        "catalog_size": len(catalog),
        "repository_skills_listed": sum(f"{NAMESPACE}:{s}" in catalog for s in SKILLS),
        "other_catalog_entries": sum(s not in {f"{NAMESPACE}:{n}" for n in SKILLS} for s in catalog),
        "event_types": ";".join(sorted(types)), "invalid_json_lines": invalid,
        "result_seen": int(result is not None), "exit_code": returncode,
    }


def run_session(cmd, work, timeout=120):
    start = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=work, env=environment(), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
    except BaseException:
        # Ctrl-C or any other interruption: the session runs in its own process group,
        # so it never sees the terminal's SIGINT. Stop the group and reap it before
        # re-raising, or it keeps running (and spending quota) after the runner exits.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise
    return parse_stream(stdout, stderr, work=work, returncode=proc.returncode,
                        timed_out=timed_out, wall_ms=round((time.monotonic() - start) * 1000))
