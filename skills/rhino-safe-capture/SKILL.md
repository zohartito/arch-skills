---
name: rhino-safe-capture
description: Rules and tooling for capturing images, sections, or data from Rhino without touching the user's live document — check for a peer session first, read saved files with rhino3dm or work in a spawned Rhino slot, and never leave temporary objects, moved cameras, or silent saves behind. Includes a partial regex PreToolUse hook that blocks recognized mutating Rhino MCP calls; it is not a sandbox or proof of read-only behavior. Use before any viewport capture, image-prompt capture, clipping-plane section, Make2D, render, or script run through the rhino-mcneel or rhino-community MCP servers, and whenever a task says "capture", "screenshot the model", "render views", or "export from Rhino".
---

# rhino-safe-capture — look at the model without changing it

The failure this prevents: capture scripts added temporary clipping planes to the user's live
document, hid them, then called `doc.Objects.Delete(id, True)`. Delete silently fails on
hidden objects, so 10 stray planes were left behind and darkened later captures. This was
logged 36 times in one studio project. A related rule was corrected 7 times: never capture from, edit, or
save another session's live model.

## Decide where to work (in this order)

1. **Is someone else on it?** List peer sessions if your harness can (e.g. a `ListAgents` tool) and read
   the project handoff notes for ownership (e.g. "session-B owns model_v21"). If a peer owns the model, wait for its "saved" message, then
   work from the saved file.
2. **Can you read instead of render?** For layers, counts, bounding boxes, units and
   object attributes, read the saved `.3dm` with rhino3dm (`python3 -c "import rhino3dm"`).
   Never touch a running Rhino for this.
3. **Need pixels or Rhino commands? Use a spawned slot:** `spawn_slot` → `open_doc` on the
   **saved** file with `clearFirst: true` and that `slot` → pass the same `slot` on every
   call → `close_slot`. Inside your own slot you can add clipping planes, move cameras and
   change display modes freely. Never pass a slot you didn't spawn: `list_slots` also shows
   the user's own Rhino under an animal name.
4. **Only when the user asked for a change to their open document in this conversation** do you
   edit the live doc. Put `# rhino-live-edit: user-approved` (C#: `// …`) in the script so
   the guard lets it through, and follow the live-edit rules below.

Every rhino-mcneel call that omits `slot` targets whatever Rhino is open: usually the user's.

## Live-edit rules (only after step 4)

- Record `doc.Modified`, the object count and the active view's camera first. Never assign
  `doc.Modified`.
- Put temporary objects on one named temp layer, keep their ids, and in `finally` call
  `doc.Objects.Show(id, True)` and `doc.Objects.Unlock(id, True)` **before**
  `doc.Objects.Delete(id, True)`. Then count by id and by temp layer; both must be 0.
  Delete the temp layer.
- Restore the camera. Never move or overwrite named views or the user's viewports.
- Never save, save-as, purge, or import into the user's document. `save_doc` goes only to a
  **new** versioned path. The guard blocks overwriting an existing file.
- Afterwards, report what changed and how you verified it was reverted.

## Capture checklist

- Name the source in the receipt: saved file path + sha256, or "live doc, user-approved".
- Use named views or explicit camera parameters inside a spawned slot. On the live doc, call
  `get_viewport_image` **without** camera arguments, because those move the view.
- Before trusting an image, check its metadata for object count and framed bounds. Empty
  or off-screen captures are common.
- Display mode, clipping planes and layer visibility are part of the evidence; list them.

## The guard hook

`hooks/rhino_live_guard.py` is a Claude Code PreToolUse hook. Register it in a project's
`.claude/settings.json` with the matcher `mcp__rhino-(mcneel|community)__.*` (see the repository README).

| Call | Decision |
|---|---|
| Script matching recognized mutating patterns (`Objects.Add*/Delete/Hide/…`, clipping planes, `rs.Add*/Delete*/…`, setters like `rs.ObjectLayer(id, layer)`, `.Modified =`, saves, `RunScript`, camera moves) and no `slot` | deny, unless the user-approved marker is present |
| `open_doc` without `slot` (would import into or clear the user's doc) | deny |
| `run_command` with Save / Purge / Delete / ClippingPlane / Import / Open / Hide / Lock / Layer and no `slot` | deny |
| `save_doc` to a path that already exists | deny |
| Scripts without a recognized pattern, viewport captures without camera args, anything with your own `slot` | allow (not proof of safety) |

The guard can't tell your slot from an adopted user slot, and it doesn't cover the
community server's single-object tools (`create_object`, `delete_object`, `boolean_*`). The
regexes also miss aliases (`rsx.DeleteObjects`), direct imports (`from rhinoscriptsyntax import DeleteObjects`),
and indirect table calls (`table = sc.doc.Objects; table.Delete(...)`). Treat arbitrary scripts conservatively:
review them before admission to the live document; if read-only behavior is uncertain, use saved-file analysis
or a spawned slot. The rules above still apply even when the hook allows a call. Tests: `python3 tests/test_rhino_live_guard.py`.
