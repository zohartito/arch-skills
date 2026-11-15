# arch-skills

Agent skills for architecture-student production work: checking exported presentation sheets, sun-hour studies,
preparing physical models for laser cutting and 3D printing, Bambu Studio print settings, and cited precedent research.
Each skill is a `SKILL.md` (instructions an AI coding agent reads) plus, for most, small Python scripts it runs.

## What works with what

- **Claude Code**: all nine skills were written for and used in Claude Code. The `rhino-safe-capture` guard is a
  Claude Code `PreToolUse` hook.
- **OpenAI Codex CLI**: `sheet-review`, `rhino-safe-capture` (rules only, not the hook), `physical-model-prep`,
  `precedent-dossier` and `sun-study` were also set up in Codex. The other four were not.
- Other agents that read `SKILL.md` folders with `name` / `description` frontmatter may work; not tested.
- The scripts are plain Python command-line tools and run without any agent.

Developed and used on macOS with Python 3.11. Windows and Linux are untested (see Limits).

## Install

```bash
git clone https://github.com/zohartito/arch-skills.git
cd arch-skills

# Python environment for the scripts
python3 -m venv .venv
.venv/bin/pip install -r requirements-arch-tools.txt

# Claude Code: link the skills you want into your user (or a project's .claude/) skills folder
mkdir -p ~/.claude/skills
for s in skills/*/; do ln -s "$PWD/$s" ~/.claude/skills/"$(basename "$s")"; done

# Codex CLI: same idea
mkdir -p ~/.codex/skills
for s in skills/*/; do ln -s "$PWD/$s" ~/.codex/skills/"$(basename "$s")"; done
```

Start a new agent session after linking. The SKILL.md files refer to "a Python with `requirements-arch-tools.txt`
installed"; that is `.venv/bin/python` above. Script paths in the SKILL.md files are relative to each skill's folder.

To turn on the Rhino guard hook for one project, add this to that project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__rhino-(mcneel|community)__.*",
        "hooks": [
          { "type": "command", "command": "python3 \"/path/to/arch-skills/skills/rhino-safe-capture/hooks/rhino_live_guard.py\"" }
        ]
      }
    ]
  }
}
```

## The skills

Every example runs from the skill's own folder. Agents are triggered by asking in plain words (the `description`
in each SKILL.md lists the phrases).

| Skill | What it does | Needs |
|---|---|---|
| `sheet-review` | Preflight of an exported sheet PDF (size, fonts, image PPI, small/placeholder text, hairlines, off-palette and legend-only colours, diff against the previous export), tile images for a visual pass, optional read-only InDesign audit | PyMuPDF; for the audit, InDesign + an `execute_extend_script` tool that is not in upstream adb-mcp yet (see Limits) |
| `rhino-safe-capture` | Rules for capturing from Rhino without changing the user's open document, plus a hook that blocks mutating Rhino MCP calls | Rhino 8 with the `rhino-mcneel` or `rhino-community` MCP server; Claude Code for the hook |
| `physical-model-prep` | Fabrication rules, laser layer conventions, starting laser settings (ULS PLS6.150D), fit clearances, mesh checks, verified USB staging | rhino3dm, trimesh |
| `bambu-print-recipes` | Bambu Studio settings and orientation for model parts (roofs, fins, railings, screens, furniture, figures), keeping supports off delicate parts | Bambu Studio; no scripts |
| `stl-fit-and-repair` | Pull parts from a saved .3dm, weld to one body, thicken thin parts, repair downloads, fit a new part to already-printed ones, render views | trimesh, manifold3d, pymeshfix, scipy, scikit-image |
| `printables-entourage` | Search and download printable people, pets, cars and plants from Printables, scale them to the model, repair, lay out one plate, keep a licence ledger | network access to printables.com; `stl-fit-and-repair` |
| `model-assembly-sheet` | 1:1 placement PDF for gluing pieces onto a base, with post holes and brass cut lengths | trimesh, matplotlib |
| `sun-study` | Sun positions and direct-sun hours on a grid through context geometry, headless (no Rhino GUI) | ladybug-core, trimesh (+ embreex), rhino3dm |
| `precedent-dossier` | Folder layout, source ledger and citation rules for precedent research, with a ledger validator | Python standard library |

### One example per skill

```bash
# sheet-review: preflight a 36x24 sheet and diff it against the last export
python3 scripts/pdf_preflight.py SHEET.pdf --out checks/sheet-review --expect-size 36x24 --compare PREVIOUS.pdf

# rhino-safe-capture: run the guard's tests
python3 tests/test_rhino_live_guard.py

# physical-model-prep: replace round post holes on the CUT layer with 1.5 mm square holes
python scripts/laser_kit.py square-holes lot.3dm --post 2.0 --burn 0.25 --out lot_square-holes.3dm

# bambu-print-recipes (no script): ask the agent
#   "what bambu studio settings for the roofs? A1, 0.4 nozzle, white PLA"

# stl-fit-and-repair: count bodies and open/non-manifold edges
python scripts/meshkit.py check roof.stl

# printables-entourage: search Printables
python -I scripts/printables.py search "sleeping cat" --limit 12

# model-assembly-sheet: build the 1:1 sheet described in sheet.json (format in the script's docstring)
python -I scripts/placement_sheet.py sheet.json

# sun-study: sun altitude/azimuth table for Dec 21
python scripts/sun_study.py --lat 34.05 --lon -118.25 --tz -8 --date 12-21 --hours 7-17 --step-min 30 --sunpath-only

# precedent-dossier: validate a dossier's ledger and citations
python3 scripts/check_ledger.py path/to/dossier
```

`python` here means the venv's Python from Install.

## Tests and evals

- `skills/sun-study/tests/` (pytest, analytic sun-angle and shading checks): `python -m pytest tests -q`
- `skills/rhino-safe-capture/tests/test_rhino_live_guard.py` (unittest)
- `skills/sheet-review/tests/seeded_eval.py SHEET.pdf --work DIR --palette "#000000,#ffffff"` plants five known
  defects in a copy of a sheet and scores the preflight against them. It needs a real sheet PDF (none is included).
- `skills/*/evals/evals.json` hold example prompts with expected behaviour, for agent evals.
- [`evals/`](evals/README.md) contains a 60-query Claude Code trigger corpus, a quota-conscious runner,
  a scoring CLI, and a synthetic PDF baseline fixture. Start with
  `python3 evals/run_triggers.py --limit 4 --dry-run`. The recorded smoke check covers 2/60 queries;
  the full sweep and paired baseline have not been run.

## Limits

- **The numbers come from one student project.** Laser settings, clearances, print recipes and real-world sizes were
  used on one studio project's models in October 2026. Many are marked "untested" or "starting point" in the files
  for that reason. Re-test on your own machines and materials.
- The SKILL.md files mention source files, handoff notes and models from that project; those are not included.
- **The InDesign audit needs a tool that is not upstream yet.** `sheet-review/scripts/run_indesign_audit.py` (and the
  MCP route in that SKILL.md) need an `execute_extend_script` tool. It comes from a fork of the adb-mcp Adobe
  connector and is not in upstream adb-mcp yet. The runner loads it from `~/adb-mcp/mcp/id-mcp.py`. Without that
  tool, the InDesign audit step does not work: run `indesign_audit.jsx` through your own ExtendScript tool, or skip
  the step. The PDF preflight does not need it. It was only used on macOS.
- `stage_usb.py` was written for macOS (`/Volumes`, and `F_NOCACHE` so the re-read comes from the stick, not the
  page cache). It imports `fcntl`, so it does not run on Windows; Linux is untested.
- `printables.py` uses the GraphQL API that the printables.com pages call. It is unofficial and may change or stop
  working. Check each model's licence before you use it.
- `sun-study` computes direct sun only: no diffuse light, radiation, or daylight metrics. Its one built-in site
  preset is `los-angeles-ca`; use `--lat/--lon/--tz` or `--epw` for anywhere else.
- `rhino-safe-capture`'s hook cannot tell a slot the agent spawned from one it adopted, and it does not cover the
  community server's single-object tools. The SKILL.md says so.
- `bambu-print-recipes` uses Bambu Studio 2.x labels and the macOS preset folder.

## License

MIT. See [LICENSE](LICENSE).
