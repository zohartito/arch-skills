#!/usr/bin/env python3
"""Run indesign_audit.jsx in the running InDesign without an MCP client (e.g. from Codex).

Reuses an execute_extend_script function from an adb-mcp InDesign server (~/adb-mcp/mcp/id-mcp.py). That function
comes from a fork of the adb-mcp Adobe connector and is not in upstream adb-mcp yet. Run it
with that server's venv:  <adb-mcp venv>/bin/python run_indesign_audit.py ...
It never launches InDesign.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ADB_MCP_DIR = Path.home() / "adb-mcp" / "mcp"
AUDIT_SCRIPT = Path(__file__).resolve().parent / "indesign_audit.jsx"


def load_indesign_server():
    sys.path.insert(0, str(ADB_MCP_DIR))
    spec = importlib.util.spec_from_file_location("indesign_server", ADB_MCP_DIR / "id-mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", default="", help="open document name, e.g. SHEET_v19_REVIEW.indd (default: active)")
    parser.add_argument("--app", default="", help="app name, needed only when the release and the Beta are both running (the error lists the names)")
    parser.add_argument("--min-ppi", type=int, default=150)
    parser.add_argument("--out", type=Path, help="write the JSON result here")
    args = parser.parse_args()

    script = AUDIT_SCRIPT.read_text()
    script = script.replace('var TARGET_DOC_NAME = "";', f"var TARGET_DOC_NAME = {json.dumps(args.doc)};", 1)
    script = script.replace("var MIN_PPI = 150;", f"var MIN_PPI = {args.min_ppi};", 1)

    result = load_indesign_server().execute_extend_script(script, app_name=args.app, undo_name="Sheet audit (read-only)")
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text if not args.out else f"wrote {args.out}")
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
