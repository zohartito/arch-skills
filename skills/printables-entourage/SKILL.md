---
name: printables-entourage
description: Find, download and prepare REALISTIC 3D-printable entourage for physical architecture models — scale people, dogs, cats, cars, plants, benches, tables — at the model's exact scale (1/4", 1/8", 1:50, 1:100), repaired for Bambu Studio, display bases cut off, thin leaves thickened, combined in an unbounded row STL for slicer arrangement, with an author/licence ledger. Downloads go through the Printables API (no browser "Save as" dialogs). Use whenever the user wants people, pets, cars, trees, plants or furniture for a model, says "entourage", "scale figures", "make it feel lively", "to scale", "find assets to print", "download the models", or asks whether a model should have people or pets at all — even if they don't name a site.
---

# Printables entourage

Evidence base: one architecture studio project, Oct 6–7 2026 — the 1/8" massing model got cars, a garden table set and benches; the
1/4" chunk model got Fab Lab Limerick 1:50 scanned people (CC BY) rescaled to 1:48, three cats and three dogs.
Scripts: `scripts/printables.py` (search / info / photo sheet / download + ledger) and `scripts/prep_entourage.py`
(scale, repair, base cut, thicken, plate). It uses `stl-fit-and-repair/scripts/meshkit.py`. Run both with
`python -I` (from the environment in the repository README) from a folder other than the downloads.

## First: should the model have it at all?

Ask what the entourage argues. A reviewer's rule at a crit: entourage only where it supports the argument. For the
chunk (unit) model the advice that held up was 2–3 people and one pet, placed where they explain the design (a person
on the shared stair half behind the screen, one in the living room that reads as social on purpose, one cat on the
terrace). Three dogs and three cats reads as clutter. Keep figures white or unpainted so they read as a layer.
Check what each model actually contains before proposing placements: the user's correction was "the unit model doesn't
have the screen".

## Workflow

1. **Search and survey.** `printables.py search "sleeping cat" --limit 12` prints id, likes, downloads and licence.
   Shortlist 3–6, then `printables.py sheet ID ID ID --out survey.png` and LOOK at the photos before downloading.
   - **Realistic only.** The user rejected low-poly ("dont use lowpoly thats weird"). Skip titles with low poly,
     faceted, voronoi, or cartoon; prefer scans and sculpted figurines.
   - **Modest and site-appropriate:** the user swapped a Porsche for the plain hatchback already in the model.
   - Check the licence fits a student review (CC BY, CC0 and Standard Digital File are fine for printing your own
     model; NoDerivs means don't remix the mesh beyond scaling and repair: note it).
   - Architecture-scale people that worked: model 1118642 (Fab Lab Limerick, 1:50, CC BY, about 5–56 MB per figure);
     556452 (JLS, 1:100, CC0). The 1:50 set is large, so take every third figure (`--every 3 --max 12`) to choose from.
2. **Download.** `printables.py fetch ID --out downloads/<group> [--match name] --ledger downloads/SOURCES-and-licenses.csv`.
   This uses the same `getDownloadLink` call the site uses. It needs no login and opens no dialogs. Do not drive Chrome
   to download: its Save dialog blocked the first attempt. Everything lands in a `downloads/` folder next to the model
   files, with a ledger row (file, model, author, licence, source URL) that you can cite on the board.
3. **Prepare at true scale.** Write a `spec.csv` (columns documented in `prep_entourage.py`), then:
   `prep_entourage.py spec.csv --src downloads --mmft 6.35 --out prepped/1-4in --plate pets-plate_1-4in.stl`
   CSV names must be basenames; input files must stay beneath `--src`, without traversal or symlinks.
   Existing outputs are refused: choose a new `--out` folder and `--plate` filename when rerunning.
   `--plate` writes one combined STL in a single row with gaps. It does not pack a usable bed or check
   bed dimensions: split into objects in the slicer, auto-arrange, and split across plates as needed.
   - Real sizes used: person 5.5–6 ft; cat 0.95 ft sitting height, 1.6 ft long lying, 1.2 ft curled; Labrador
     sitting 2.0 ft; French bulldog 1.2 ft; Great Dane 3.0 ft; agave 3 ft across; Mini 12.7 ft long; hatchback
     14.3 × 6.7 × 4.4 ft. Read the printed sizes and real equivalents the script reports, and fix any wrong one.
   - Scale-figure sets use `source_scale` (1:50 → 1/4" = ×50/48; → 1/8" = ×50/96) instead of `size_ft`.
   - `cut_base=1` removes round display bases. The cut sits 0.2 mm above the base rim; check the feet in the render.
   - `grow_mm`: leaves are paper-thin once scaled (about 0.2 mm at 1/8"). Use 0.12 at 1/4" and 0.14 at 1/8". A
     palm made of flat card-like parts and a detailed agave were still too thin, so they were dropped.
   - Cars that are open render meshes inside the Rhino model: pull them with `stl-fit-and-repair/rhino_extract.py`
     and fuse them with `meshkit.py solidify` (the Ford Focus).
4. **Check and show.** Every item must report `bodies 1, bad edges 0`. Render the plate
   (`stl-fit-and-repair/scripts/render_views.py plate.stl --out plate.png`) and look before sending. Without the
   render, an agave reduced to one leaf would have gone out. Keep each plate under about 20 MB (decimate to
   60k faces per figure); a 30 MB file did not reach the user's phone.
5. **Reply** with the plate file, a table of each piece's printed size, the print recipe (`bambu-print-recipes`:
   figures and pets use a 0.2 nozzle, 0.08 mm layers, tree supports on build plate only, 3 mm brim, printed
   standing; furniture prints upside down), and where each piece goes on the model.

## Furniture taken from the model itself

The project's garden table and benches came from the Rhino furniture layers rather than Printables. Details too fine to
print, such as 0.3 mm slats at 1/8", became one solid plank top: tell the user. Print furniture upside down (top on
the bed, no supports) and add it to the 1:1 placement sheet (`model-assembly-sheet`).
