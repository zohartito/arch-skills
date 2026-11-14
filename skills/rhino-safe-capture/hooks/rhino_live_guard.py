#!/usr/bin/env python3
"""PreToolUse guard: stop Rhino MCP calls from silently changing the live document.

Denies (with instructions the agent can act on) when a call would mutate the user's open
Rhino document: mutating script code, importing into or clearing the live doc, running
save/purge/delete commands, or saving over an existing file. Allows read-only scripts,
work in a slot the agent spawned (`slot` argument), and live edits the user explicitly
approved — marked by the comment `rhino-live-edit: user-approved` in the script.
"""
import json
import re
import sys
from pathlib import Path

APPROVAL_MARKER = "rhino-live-edit: user-approved"
CODE_TOOLS = {
    "mcp__rhino-mcneel__run_python",
    "mcp__rhino-mcneel__run_csharp",
    "mcp__rhino-community__execute_rhinoscript_python_code",
    "mcp__rhino-community__execute_rhinocommon_csharp_code",
}
COMMAND_TOOLS = {"mcp__rhino-mcneel__run_command", "mcp__rhino-community__run_command"}
MUTATING_CODE = [
    r"AddClippingPlane|ClippingPlaneObject",
    r"\.Objects\.(Add\w*|Delete|Hide|Show|Lock|Unlock|Replace|Transform|ModifyAttributes|Purge)\b",
    r"\.(Layers|Groups|Materials|InstanceDefinitions)\.(Add\w*|Delete|Purge|Modify\w*|SetCurrentLayerIndex)\b",
    r"\.CommitChanges\s*\(",
    r"\.Modified\s*=",
    r"\.(Save|SaveAs|Write3dmFile|WriteFile)\s*\(",
    r"RhinoApp\.RunScript|\brs\.Command\s*\(",
    r"\.NamedViews\.(Add|Delete|Restore)|SetCameraLocation|SetCameraTarget|\.SetCameraDirection|ZoomExtents|ZoomBoundingBox",
    r"\brs\.(Add|Delete|Hide|Show|Lock|Unlock|Move|Copy|Rotate|Scale|Mirror|Transform|Purge|Rename|Join|Explode|Split|Trim|Boolean|Extrude|Loft|Offset)\w*\s*\(",
    r"\brs\.(ObjectLayer|ObjectColor|ObjectName|ObjectPrintWidth|LayerVisible|LayerLocked|LayerColor)\s*\([^()]*,",
    r"\brs\.CurrentLayer\s*\(\s*[^)\s]",
]
MUTATING_COMMAND = r"(?i)\b_?-?_?(Save\w*|Purge|Delete\w*|ClippingPlane|Import|Open|New|Insert|Hide|Lock|Layer)\b"


def collect_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() if key != "slot" for text in collect_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in collect_strings(item)]
    return []


def deny(reason: str):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


RULES = (
    "Rules (rhino-safe-capture skill): (1) check ListAgents first — another session may own this "
    "model. (2) For captures and experiments: spawn_slot, then open_doc the SAVED .3dm into that "
    "slot with clearFirst=true, pass that slot on every call, close_slot when done — or read the "
    "saved file with rhino3dm. (3) Only if the user asked in this conversation for this exact change to "
    f"their live document, add the comment `{APPROVAL_MARKER}` to the script and retry. Temporary "
    "objects must be shown and unlocked before Delete, then verified gone; never set doc.Modified."
)


def main():
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    in_spawned_slot = bool(tool_input.get("slot"))

    if tool == "mcp__rhino-mcneel__save_doc":
        target = Path(str(tool_input.get("path", ""))).expanduser()
        if target.exists():
            deny(f"Blocked: save_doc would overwrite the existing file {target}. Save to a new, versioned "
                 "path, or let the user save their own document. " + RULES)
        return

    if tool == "mcp__rhino-mcneel__open_doc" and not in_spawned_slot:
        action = "delete every object in" if tool_input.get("clearFirst") else "import geometry into"
        deny(f"Blocked: open_doc without a slot would {action} the live Rhino document. " + RULES)

    if tool in COMMAND_TOOLS and not in_spawned_slot:
        command = " ".join(collect_strings(tool_input))
        match = re.search(MUTATING_COMMAND, command)
        if match:
            deny(f"Blocked: Rhino command '{match.group(0)}' would change the live document. " + RULES)
        return

    if tool in CODE_TOOLS and not in_spawned_slot:
        code = "\n".join(collect_strings(tool_input))
        if APPROVAL_MARKER in code:
            return
        for pattern in MUTATING_CODE:
            match = re.search(pattern, code)
            if match:
                deny(f"Blocked: this script would change the live Rhino document ('{match.group(0)}'). " + RULES)


if __name__ == "__main__":
    main()
