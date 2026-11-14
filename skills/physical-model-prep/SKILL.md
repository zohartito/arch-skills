---
name: physical-model-prep
description: Prepare physical architecture studio models for fabrication - 3D-print STLs and laser-cut .3dm files generated from the saved Rhino model, with the scales, materials, layer colours, fit clearances, measured laser burn, laser settings per material (basswood, plywood, MDF engrave, mat board) and USB hand-off that one real studio project's models (Oct 2026) actually used, plus the rules the user's corrections set. Use when asked for a "laser file", to "laser cut" or "score" or "engrave" parts, "laser settings", square or round "post holes", "kerf", to "3D print the model", to build a "massing model" or "chunk model", for a "cut list", for anything at the "fab lab" or the "plotter USB", or when making a "model base" or "lot insert".
---

# Physical model prep

Evidence base: one architecture studio project's physical models (a 1/8" massing model and a 1/4" "chunk" model),
Oct 2-7 2026. The numbers below come from that project's generator scripts, cut lists and session notes, which are
not part of this repository. Status words say how far each value was tested: "measured", "tested", "used", "untested".
These are one project's values: re-measure the class base, sheets and machine before reusing them.

Related skills: `stl-fit-and-repair` (one-piece STLs, weld, fit to printed parts, repair, renders),
`bambu-print-recipes` (slicer settings, keeping supports off delicate parts), `printables-entourage` (people, pets,
cars, plants at scale), `model-assembly-sheet` (1:1 placement PDF, brass cut lengths, post names). This skill keeps
the fabrication rules, materials, laser files and lab hand-off.

## 1. Non-negotiables (from the user's corrections)

- **Massing = exterior envelope only, applied consistently.** No stray interior partitions (an agent left closet
  returns in the walls print; the user rejected it).
- **Perforated screens are perforated, never solid panels.**
- **Interior black is brushed, never sprayed**; blue painter's tape over window openings from outside first (not duct
  tape).
- **No burn marks on visible faces.** Blue tape on the good face, lowest power that cuts, 400-grit edge sand; no
  engraving on the lot; hide score lines under parts.
- **No visible seam on a part meant to read as one piece.** A two-half printed lot was rejected even with a dovetail
  ("i wish it was one piece"); fix = laminate full-size laser layers instead.
- **Laser parts that drop into printed parts must clear everything above them** (furniture blocks, stair), not only
  walls: the first floor-wood version sat on the furniture.
- **Lot-top features are the user's call and changed three times** (path indents wanted, then removed, then back). Ask.
- **Every model carries furniture, scale figures, a graphic scale and a north arrow.**
- **Generate from the saved canonical .3dm, read-only, visible objects only, and record its SHA-256.** Never derive
  dimensions from images.
- Later corrections:
  - **Pieces meant to read as one piece have no extra blocks or lines.** A bench block on the garden screens and
    visible joint lines were rejected ("it should just be one piece"). Small "squares" on a part get questioned:
    explain or remove them.
  - **Parts printed on a side have a flush bed face.** Post tabs were removed from the bridges.
  - **Features that need support get removed when the read survives**, such as the top rail over the pickets.
  - **Check what each model actually contains before adding to it.** "The unit model doesn't have the screen."
  - **Realistic entourage only, no low-poly; modest cars**; see `printables-entourage`.
  - **Laser the scoring rather than hand-score it** ("its less clean"): the chunk terraces got laser deck-board scores.
  - **When the user says skip the test strip, pick one value, say why, and record it as untested.**
  - **Files already printing are not stale by default:** say exactly what changed and whether the printing version
    still works (the bridges with the old round post holes did) before suggesting a reprint.

## 2. Scales and materials actually used

| Part | Scale / size | Material, process |
|---|---|---|
| Massing (houses, roofs, bridges) | 1/8" = 1'-0" (3.175 mm/ft) | white PLA, 0.4 nozzle, 0.20 mm layers (small parts 0.12) |
| Window screens (12) | 1/8", 0.48 mm thick | white PLA, 0.2 nozzle, 0.12 layers, no supports; fallback white 110 lb cardstock |
| Chunk (stair + unit slice) | 1/4" = 1'-0" (6.35 mm/ft), 4.5 x 7.25 in | PLA 0.16 layers, supports off; stair black PETG |
| Chunk floor wood | 1/16" (1.59 mm) basswood, 12x12 sheet | laser, cut only |
| Chunk base + massing tag | 8.5 x 11 in base, 3 x 1.25 in tag | 1/8" basswood plywood 12x24, laser cut/score/engrave |
| Lot insert (one piece) | 6.25 x 19.30 in, 3/4" | 4 x 3/16" basswood ply (4 x 4.76 = 19.05 mm), 2 layers per 18x23 sheet |
| Grass stencil | lot outline, 19.3 x 6.3 in | 4-ply mat board 16x20 (or 1/8" ply, same file) |
| Bridge posts (8) | 2 mm square brass tube, raw satin | hacksaw + miter box; lengths from `model-assembly-sheet` |

Earlier versions of the same project used other scales and finishes (a 3/16" chunk, spray-painted metal). Check the
latest model guide before reusing any row.

## 3. Laser file conventions

- Rhino .3dm, **inches, true size**, hairline polylines, colour by layer (`ColorFromLayer`). Exact layers (as in `scripts/laser_kit.py`):
  `CUT (red)` 255,0,0 = cut through · `SCORE (blue)` 0,0,255 = surface line · `ENGRAVE (black)` 0,0,0 = raster ·
  `REFERENCE - do not cut` 0,170,0 = 32 x 18 in bed + material-sheet outline + labels. **Turn REFERENCE off before sending.**
- Piece labels are TextDots on REFERENCE: **photograph the screen before hiding it**, and ship a placement PNG
  (`preview_1-floor-wood-v2-WHERE-EACH-PIECE-GOES.png`).
- Every file has a **0.5 in test square** on CUT; a card file gets a 0.4 in hole test piece.
- **Inside-to-outside:** add holes to the file before outlines, and also ask for inside-to-outside sorting in the driver.
- **Holding tabs:** 0.04 in (1 mm) bridges hold stencil islands; overpowering burns them away.
- **Kerf allowance (assumed ~0.1 mm/side, never measured):** screen holes drawn 0.10 mm smaller in diameter;
  floor pieces 0.15 mm drawn gap; ply lot 0.05 mm drawn clearance. The measured burn in section 5 is larger.
- Hide marks: score lines 0.5 mm inside each house footprint so the house covers them.
- Placement: sheet outline at 0.25 in offset from the bed origin; an 18x23 sheet fills the bed's 18 in side, push it
  into corner (0,0). Piece spacing 0.20 in.
- File names say order, part, material, thickness and sheet: `5_LOT-PLYWOOD-SHEET-A_top+layer2_3-16in-ply_18x23.3dm`.
- Never put styrene in the laser (toxic fumes).
- **Set blue (score) to run before red (cut)**, so scores land before pieces drop loose and shift.
- **Clip each score line to its own part:** shared edges between two floor pieces drew the score twice. Scores that
  must stay hidden sit 0.4-0.5 mm inside the part.
- **Subset files when only some pieces need recutting** (`..._v3_UPPER-ONLY_TERRACES-SCORED.3dm`): same layout, same
  sheet position, so pieces already cut still match.
- **Engraving a board cut elsewhere** (table-sawed MDF chunk base): move the artwork so the board's corner is the bed
  corner (0,0), draw the board edge on REFERENCE, and leave CUT empty.
- **Square posts get square holes,** turned to the post's plan angle (`scripts/laser_kit.py square-holes`). Round
  holes let square brass wobble.

## 4. ULS PLS6.150D starting settings (a university lab laser, 2 x 75 W)

**Starting points, not yet confirmed by a test cut.** Agent-suggested during the lab session; no test-cut result was
recorded. Machine identity, "2 x 75 W" and the previous user's leftover values (red 100%/72%, Z 0.060") come from
reading a screenshot of the driver.

Prefer the driver's **Materials Database** (material + thickness, intensity adjustment 0). Manual Control fallback:

| Material (Z-axis = thickness) | Red cut P / S / PPI | Blue score | Black engrave |
|---|---|---|---|
| 1/16" basswood (0.0625") | 60% / 15% / 500 | 5% / 100% / 500 (deck boards; 4 if too dark) | - |
| 1/8" plywood (0.125") | 100% / 8% / 500 | 10% / 100% / 500 | 20% / 100% / 500 |
| 3/16" plywood (0.1875") | 100% / 5% / 500 (a 2nd pass beats slowing down) | 6% / 100% / 500 untaped, 8% taped | - |
| MDF (enter the board's real thickness) | - (table-sawed) | 8% / 100% / 500 | 40% / 100% / 500 raster (50 if faint) |
| Mat board (0.060") | 50% / 20% / 300 | - | - |
| Cardstock (0.012") | 15% / 50% / 300 | - | - |

The basswood score, 3/16" score and MDF rows were given and used at the lab. The only reported physical result is
the 3/16" cut burn (section 5); ask how the scores and engraving came out and record it. **Tape:** tape absorbs part
of a low-power score, so a taped score needs about 2 points more power. On one sheet the user chose no tape on the
lot top layer and sanded instead. That is the user's call per sheet, so ask; the rule of tape on visible faces still
applies where burn marks would show. **Same settings for the test piece and the real part**, or the test predicts nothing.

Protocol, every sheet: blue tape on the good face; Z-axis = material thickness (wrong focus = wide kerf, burning, uncut
spots); air assist on; cut the test square first. **Not through: add a second pass (burns less than going slower;
it also widens holes slightly), or lower speed 2-3 points; re-run red in place without moving the sheet. Charred:
raise speed.** Weigh the sheet flat (a warped sheet goes out of focus). Several fast passes burn less than one slow pass. Check a corner is
through before lifting; small parts can drop through the honeycomb. Stay with the machine (mat board/card can flare).
Record the settings that worked back into this file once a cut is confirmed.

## 5. Fit and clearance values

| Interface | Value | Physical result |
|---|---|---|
| Printed lot in CNC hole of 3/4" MDF base | 0.3 mm/side | **Tested: "not snug, goes in and out easy"**; would drop through the through-hole |
| Same, retuned | 0.15 mm/side | not printed |
| Hole-derived clearance | `max(158.75-W, 490.19-L)/2 + 0.15`; corner R = measured + 0.2 mm (printed radius gauge) | method |
| Sliding dovetail v1 | 1:4 flare, 0.25 mm gap | **Tested: ~1 mm slide play** (play = gap / sin(flare)) |
| Sliding dovetail v2 | 1:2 flare, 0.1 mm gap | predicted ~0.2 mm, not tested |
| House pocket | footprint + 0.25 mm, 1.0 mm deep; walls seat 1.0 mm | unknown |
| Post hole for 2 mm sq tube | 3.0 mm dia (diag 2.83), 6 mm deep, >= 1.5 mm from pocket | unknown |
| **Laser burn, 3/16" ply at 100/5/500** | 3.0 mm drawn circle | **Measured: cut ~3.6 mm, ~0.3 mm/side; the 2 mm square posts wobbled** |
| Square hole for 2 mm sq brass | drawn 1.5 mm (post - 2 x 0.25), turned to post plan angle | chosen without a test strip (the user's call); cut and fit not reported |
| Post length | above-ground height + 6 mm socket; +-0.3 mm OK | unknown |
| Ply lot socket | one layer (4.76 mm), houses 1 mm higher -> original post lengths | superseded |
| **Post length, flat ply lot** | above-lot + 4.8 mm socket + **1.0 mm** (walls' 1 mm seat plinth sits on the flat lot) | lengths given; fit not reported; see `model-assembly-sheet` |
| One-piece roof onto PRINTED walls | printed walls grown 0.15 mm, subtracted; drop-on path checked | printing started; fit not reported; see `stl-fit-and-repair` |
| Bridge fins / plates | 1.2 mm minimum | **0.7 mm snapped during support removal** |
| Floor wood v1 | 0.004 in/side around walls only | **Failed: sat on furniture blocks** |
| Floor wood v2 | 0.15 mm gap to every wall/block; slide-in strips need wood + 0.3 mm headroom | unknown |
| Merged roof boxes | grown 0.15 mm/side to overlap the roof | printed, fit unknown |
| Chunk stair | seats in a 4 mm pocket carved from the ground plate | unknown |

Rule: print a 15-minute joint/fit coupon or cut a test square before the full part, and ask the user for the
physical result before tightening or loosening anything.

## 6. 3D-print checks (what the generators verified)

- **Closed after reload:** export, reload, drop triangles float32 STL rounding made zero-area, re-export, assert
  `is_watertight and is_winding_consistent`.
- **Slivers:** drop zero-volume bodies < 0.05 mm3 left by thickening (one run dropped 122); drop recess slivers
  < 0.3 mm; fill raised strips < 1.0 mm.
- **Minimum features:** 0.6 mm walls, 0.7 mm bridge plates/blades; thinner true-scale parts are thickened and
  reported (bridge edge ~0.58 -> 0.7 mm).
- **Fine perforation:** true holes 0.92 mm, bars 0.31 mm need a 0.2 nozzle; a COARSE version keeps the open ratio
  with bars >= 0.45 mm (~2 lines of 0.2 nozzle). Print a TRUE-vs-COARSE coupon first.
- **Bed:** fits a 256 mm cube with 5 mm margin, placed on z = 0.
- **Cuts:** split 0.02 mm either side of a slab face, never on it (zero-thickness films); omit zero-thickness
  surfaces (panel joints, linings).
- **Separate closed meshes are not one printable body:** one earlier version had 66 closed meshes, none unioned.
- **Bambu Studio import resets CLI custom settings to defaults:** re-check settings after opening, slice, inspect the
  preview (see `bambu-print-recipes`).
- Run `scripts/check_mesh.py` (needs trimesh; see the repository README for the environment) on every STL;
  thin-wall output is a warning with coordinates, judge it in the slicer preview.
- One-piece, open-edge and fit problems: `stl-fit-and-repair` (`meshkit.py check` counts real bodies and Bambu-style
  bad edges; `fit_to_mates.py` proves a part drops onto printed ones; `render_views.py` before claiming a fix).
- Loose fragments under 2 mm3 are deleted, never strutted: auto-struts printed as stray bars that drew supports, and
  the user had them removed from the walls.

## 7. Hand-off to the lab

- Stage with `scripts/stage_usb.py FILES_OR_DIR --dest "/Volumes/<USB>/<folder>"`: copies, fsyncs, re-reads (no cache on
  macOS), compares SHA-256, writes `MANIFEST-SHA256.txt`, refuses an unmounted volume, skips dotfiles and `_superseded*`, and
  refuses to silently overwrite a different same-name file. Exit 1 = do not take the USB.
- A replacement must get an unmistakable name (`..._v2-NEW...`): a same-name overwrite looked identical at the lab and the
  stick may have been pulled before the write finished. Eject (`diskutil eject`) before unplugging.
- Keep superseded files and previews off the stick (`_superseded/`); remove a preview that shows old pieces.
- One `READ ME - cut list.txt` per USB: colour meanings, per file material/thickness/sheet/what it makes, cut order, finishing
  notes. Include KEY PDFs and placement PNGs.
- Lab hours and closures change; check them and book slots ahead.

## 8. Pre-flight checklist (before calling any fab file "ready")

- [ ] Source .3dm path + SHA-256 recorded; generated read-only from the saved model, visible objects only
- [ ] Exterior envelope only for massing; screens perforated; nothing above a floor left uncleared for drop-in parts
- [ ] Scale, units (inches for laser, mm for STL) and sheet/bed size confirmed against the brief and real stock
- [ ] Laser: 4 named layers with exact RGB, REFERENCE has bed + sheet outline + labels, 0.5 in test square, holes before outlines, tabs on islands
- [ ] No burn on visible faces: no engraving/score where it shows, score lines hidden under parts
- [ ] STL: `check_mesh.py` PASS (watertight, winding, bed); thin spots and slivers reviewed
- [ ] Fit values traced to a physical test result, or labelled untested and a coupon/test square queued
- [ ] Laser settings labelled "starting points" unless a test cut confirmed them
- [ ] `stage_usb.py` exit 0, manifest on the stick, no superseded or stale previews, cut-list README present
- [ ] Status words kept distinct: generated / verified-file / on USB / cut / fitted
