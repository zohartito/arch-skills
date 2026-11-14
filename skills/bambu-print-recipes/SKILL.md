---
name: bambu-print-recipes
description: Bambu Studio settings for printing architecture model parts on a Bambu A1 / P1S / X1 — roofs, thin fins and bridges, walls with railings, perforated screens, furniture, cars, scale figures and pets — plus how to orient each part, keep tree supports OFF delicate parts (build-plate-only, XY distance, support painting/blockers), brims for tall thin parts, filament-slot traps, and what to do when a part is already printing and the file changes. Use whenever the user asks "what settings", "Bambu settings for X", "supports are touching it", "should I reprint", sends a Bambu Studio / Handy screenshot, or is about to slice any model part — even if they don't say Bambu.
---

# Bambu print recipes for model parts

Evidence base: one architecture studio project's physical models, Oct 4–17 2026, on a Bambu A1 (0.4 and 0.2 nozzles,
white PLA Basic, Textured PEI). "Used" means printed with these settings. Physical results are recorded only where
the user reported them; ask for the
result after a print and add it here. Values are Bambu Studio 2.x labels.

## Before any recipe

- **Ask or read which printer, nozzle, plate and filament are loaded** (from the screenshot). A PETG spool sitting in
  slot 2 means every object must be on slot 1, or Bambu adds a purge tower and colour swaps.
- **Settings prepared outside the app (CLI or a script) were reset to preset defaults when the file was opened in
  Bambu Studio** (seen twice, most recently Oct 17). Read the settings back after every import rather than trusting the file.
  What worked on Oct 17:
  - Write a user process preset (`from: User`, `inherits: <system preset>`, only the changed keys) into
    `~/Library/Application Support/BambuStudio/user/<uid>/process/`, with a matching `.info` file.
  - Give it the exact name the 3MF's `print_settings_id` uses, and open the file in a new instance (`open -n -a BambuStudio file.3mf`).
  - Click the orange reset arrow next to the process name. Check the Strength and Support tabs, then slice in the GUI and save.
- **Orientation is part of the design.** Leave parts as they load when they were exported bed-ready. Do not use
  Auto Orient or "lay on face", and say "no" when Bambu asks to split one piece into parts.
- **Slice, then scrub the Preview slider** where supports could touch something fragile. Supports belong only under
  decks, cars and leaning parts.
- Keep at least 5 mm between objects so brims and trees don't merge.

## Recipes

| Part | Nozzle / preset / layer | Walls, infill | Supports | Adhesion | Orientation | Status |
|---|---|---|---|---|---|---|
| One-piece roof with standing seams (1/8") | 0.4, "0.16mm Optimal", 0.16 (first 0.20), Arachne | 3 walls, top 5 / bottom 4, 15 % gyroid | tree(auto) Tree Slim, 30°, build plate only **off**, top Z 0.2, 2 interface | outer brim 5 mm, no ironing | seams up, flat underside down | used Oct 5 |
| Fin bridge printed on its side | 0.4, 0.12 | 2 walls, 15 % | Tree Slim, build plate only **on**, top Z 0.25, 2 interface | brim 8 mm (55 mm tall on a thin edge) | flat side down, fins up, as loaded | used; the 0.7 mm fins snapped, then printed at 1.2 mm |
| Mixed plate (bridges, cars, furniture, screens) on A1 | 0.4, "0.12mm Fine @BBL A1" | 2 walls, 15 % gyroid | Tree Slim, 30°, build plate only **on**, top Z 0.25, 2 interface | outer brim 5 mm; bridges 8 mm per object | see the orientation rules below | used Oct 6 |
| House walls with terrace railings | 0.4, 0.16–0.20 | 3 walls | build plate only **on**, support/object **XY distance 1.0 mm** (default 0.35), remove small overhangs on, top Z 0.25; paint pickets **Block** (L), add support blockers | brim 5 mm | upright | **not enough on its own**: the trees still touched the pickets and the terrace posts broke. Fixed by changing the geometry (below) |
| Window screens, perforated 0.48 mm | 0.2, 0.12 | – | none | – | flat | used (see `physical-model-prep`) |
| Continuous garden screens | 0.4, 0.12 | 2 walls | none | brim 5 mm | standing, as loaded | used Oct 6 |
| Garden table, benches, winter sun bench (1/8") | 0.4, 0.12 | 2 walls | none | brim 3 mm | **upside down**: top or seat on the bed | used Oct 6 |
| Cars (1/8") | 0.4, 0.12 | 2 walls | tree, build plate only (under the body) | brim 5 mm | wheels down | used Oct 6 |
| Scale people and pets (1/4", 6–37 mm) | **0.2**, 0.08 | 2 walls | tree, build plate only (under the dogs' bellies) | brim 3 mm | standing | recipe given Oct 7; result not reported |
| Chunk (1/4") slices | PLA 0.16 | – | off | – | as generated; stair in black PETG | see `physical-model-prep` |
| Downpipe, 1.7 mm square × 62 mm | lay it flat if printed | – | – | – | flat | a 1.5–2 mm brass or styrene rod cut to length is better |
| Site-model context buildings (3/32", 50–77 mm tall, 1'-0" eaves, 1/16" window recesses), team spec | 0.4, "0.12mm High Quality" (team-shared P2S and A1 presets) | 3 walls, top 6 / bottom 5, **3 % grid** (team spec) | tree(auto) Tree Slim, 30°, build plate only **on**, **support critical regions only on**, XY 1.0, top Z 0.24 (supports only the real cantilevers, e.g. a 10 mm gable ledge; no trees under every 2.4 mm eave) | outer brim 5 mm, Textured PEI | upright, base down, ≥14 mm apart | sliced Oct 17 (P2S 6 h 50 min / A1 7 h 56 min); result not reported yet |

## When supports keep touching something delicate

Work in this order; each step is cheaper than reprinting a broken part:
1. Set build plate only **on**, raise XY distance to 1.0 mm, and turn on remove small overhangs.
2. Paint the area with Support painting (**L**) → **Block**, or right-click → **Add support blocker** over it, then re-slice.
3. If the Preview still shows contact, **change the geometry** instead (see `stl-fit-and-repair` → Design the supports
   out). Remove the overhang the part doesn't need (the top rail), tie hanging ends back to the wall, print on a flush
   side, or print the delicate part flat as its own piece and glue it on.
Tell the user plainly when settings alone won't do it. Rather than suggesting another round of settings, offer the
geometry fix with a time estimate ("about 15 minutes for me").

## When a part is already printing and the file changes

The user asked mid-print, "the bridges are already printing… should I reprint?" Before saying yes, compare the two
versions. Say exactly what differs and whether the part printing now still works with what's already built (the old
post holes, the printed walls). Only recommend a reprint for a fit or visible-quality reason. If another agent is still
changing the model, say "wait for the next version" instead of producing files to chase it.

## After printing

Peel supports slowly and snap them toward the part, not away from it. Trim brims with a blade. Sand only the faces that
sit on another part: roof undersides, bridge ends, screen bottoms, furniture leg tops. Never sand seams or visible
ribs. For brass posts, see `model-assembly-sheet`.
