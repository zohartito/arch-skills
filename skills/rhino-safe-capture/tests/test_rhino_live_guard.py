#!/usr/bin/env python3
"""Cases for the live-document guard. Run: python3 tests/test_rhino_live_guard.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "rhino_live_guard.py"
FAILED_CAPTURE = """
import Rhino
doc = __rhino_doc__
plane_id = doc.Objects.AddClippingPlane(Rhino.Geometry.Plane.WorldXY, 100, 100, view_ids)
doc.Objects.Hide(plane_id, True)
try:
    capture()
finally:
    doc.Objects.Delete(plane_id, True)
"""
READ_ONLY_AUDIT = """
import rhinoscriptsyntax as rs
doc = __rhino_doc__
layers = [layer.FullPath for layer in doc.Layers]
current = rs.ObjectLayer(some_id)
print(len(layers), doc.Modified, current)
"""


def decision(tool: str, tool_input: dict) -> str:
    event = {"tool_name": tool, "tool_input": tool_input, "hook_event_name": "PreToolUse"}
    completed = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True, check=True)
    if not completed.stdout.strip():
        return "allow"
    return json.loads(completed.stdout)["hookSpecificOutput"]["permissionDecision"]


class GuardCases(unittest.TestCase):
    def test_logged_failure_is_blocked(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": FAILED_CAPTURE}), "deny")

    def test_read_only_audit_passes(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": READ_ONLY_AUDIT}), "allow")

    def test_user_approved_marker_passes(self):
        script = "# rhino-live-edit: user-approved\n" + FAILED_CAPTURE
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": script}), "allow")

    def test_spawned_slot_passes(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": FAILED_CAPTURE, "slot": "slot-1"}), "allow")

    def test_community_server_is_guarded(self):
        self.assertEqual(decision("mcp__rhino-community__execute_rhinoscript_python_code", {"code": "rs.DeleteObjects(ids)"}), "deny")

    def test_setter_blocked_getter_allowed(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": "rs.ObjectLayer(obj, 'TEMP')"}), "deny")
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": "rs.ObjectLayer(obj)"}), "allow")

    def test_hiding_unsaved_changes_blocked(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_csharp", {"script": "doc.Modified = false;"}), "deny")

    def test_camera_moves_blocked(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_python", {"script": "vp.SetCameraLocation(pt, True)"}), "deny")

    def test_open_doc_into_live_doc_blocked(self):
        self.assertEqual(decision("mcp__rhino-mcneel__open_doc", {"path": "/tmp/a.3dm", "clearFirst": True}), "deny")
        self.assertEqual(decision("mcp__rhino-mcneel__open_doc", {"path": "/tmp/a.3dm", "clearFirst": True, "slot": "s1"}), "allow")

    def test_save_doc_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "model_v21.3dm"
            existing.write_text("x")
            self.assertEqual(decision("mcp__rhino-mcneel__save_doc", {"path": str(existing), "slot": "s1"}), "deny")
            self.assertEqual(decision("mcp__rhino-mcneel__save_doc", {"path": str(Path(folder) / "copy.3dm")}), "allow")

    def test_mutating_commands_blocked(self):
        self.assertEqual(decision("mcp__rhino-mcneel__run_command", {"command": "-_Save"}), "deny")
        self.assertEqual(decision("mcp__rhino-community__run_command", {"command": "_Purge"}), "deny")
        self.assertEqual(decision("mcp__rhino-mcneel__run_command", {"command": "_Zoom _All _Extents", "slot": "s1"}), "allow")

    def test_other_tools_untouched(self):
        self.assertEqual(decision("mcp__rhino-mcneel__get_viewport_image", {"view": "top"}), "allow")


if __name__ == "__main__":
    unittest.main(verbosity=1)
