---
name: sheet-review
description: Preflight and review an exported presentation sheet (PDF) and its InDesign source before calling it done — page size, embedded fonts, image PPI, small and placeholder text, scale notations, hairlines, off-palette and legend-only colors, a change diff against the previous export, InDesign overset / links / placed-drawing scale / missing fonts, then a tile-by-tile visual pass for stray linework and legend-to-symbol mismatches. Use when the user says "check the sheet", "review the PDF", "is the board ready", "preflight", "before I print / plot / submit", after any InDesign export, or before reporting a layout as verified.
---

# sheet-review — export → evidence → verdict

A fit-to-screen look cannot see a 0.3 pt stray line on a 36×24 sheet. In one studio project, "PDF
reviewed" was claimed while stray bed linework and a colored legend over uncolored symbols
went through, and that miss is logged 30 times. This skill makes the review cover every
tile, and it keeps what a script proved separate from what the visual pass saw.

Scripts live in this skill's `scripts/` folder; run commands from the skill folder.

## Order

1. **Pin the artifact.** Record the PDF path and its INDD, with the sha256 and mtime of both.
   Review the exported PDF, not a description of it.
2. **InDesign audit** (when the INDD is open). It only reads and never launches InDesign.
   - MCP: read `indesign_audit.jsx`, set `TARGET_DOC_NAME` to the document name, and pass the
     text to an InDesign MCP tool named `execute_extend_script` (see the repository README). Pass `app_name`
     when both the release and Beta InDesign are running.
   - Without MCP (Codex, shell):
     `<adb-mcp venv>/bin/python scripts/run_indesign_audit.py --doc NAME.indd --app "Adobe InDesign 2026 (Beta)" --out <checks>/indesign-audit.json`
   - If `unsavedChanges` is true, the PDF does not represent the live layout. Say so.
3. **PDF preflight:**
   ```bash
   python3 scripts/pdf_preflight.py SHEET.pdf --out <checks>/sheet-review-<date> \
     --expect-size 36x24 --palette <project>/standards/linework.md --compare PREVIOUS.pdf
   ```
   Dependencies are PyMuPDF, numpy, Pillow and scipy (all in `requirements-arch-tools.txt`).
   Exit 1 means a FAIL. Outputs are `report.md`, `report.json`, `p<N>-overview.png` with the
   tile grid labeled, `tiles/p<N>-r<row>c<col>.png` at 150 dpi (`--tile-dpi 300` for fine
   linework) and `p<N>-diff.png`. Always pass `--compare` when a previous export exists: the
   changed-region list is the cheapest way to catch a stray line or an accidental move.
4. **Visual pass on every tile, in order.** For each tile write `clean` or the issue with
   its tile id. Look at the overview first for composition at fit-page distance. Then, per tile:
   - **Stray linework:** construction lines, duplicates, lines crossing furniture, beds or
     text, lines outside a drawing frame, broken hatch boundaries.
   - **Legend ↔ symbol:** every legend swatch appears on the drawing it keys, and every
     colored category on the drawing is in the legend. A colored legend over uncolored
     symbols is a fail. `swatch-only-color` findings point at suspects.
   - **Line hierarchy:** cut/poché heaviest, then medium, then light, per the project's
     linework standard.
   - **Scale:** each stated scale (the preflight lists every notation) matches the placed
     size. A placed drawing that isn't at 100% in the audit makes its stated scale wrong
     unless the label was changed to match. Scale bars and north arrows are where the
     standard asks for them. NTS appears only where intended.
   - **Text:** readable at print size, nothing clipped, no placeholders, consistent titles.
   - **Images:** pixelation or banding. Section cut marks match the section titles.
5. **Report in three columns:** *verified by script* / *seen in visual pass* / *not checked*.
   Keep status words exact: exported ≠ printed ≠ submitted. Never call a sheet ready with
   an open FAIL, an unreviewed tile, or unsaved INDD changes.

## Reading the automated findings

| Check | Meaning | Watch for |
|---|---|---|
| `page-size` FAIL | wrong size or orientation | — |
| `font-not-embedded` FAIL | the plotter may substitute | — |
| `low-ppi-image` | effective PPI at placed size | bbox can extend past the page on cropped images |
| `small-text` | spans below `--min-text-pt` (6) | sizes are listed, the smallest is located |
| `placeholder-text` | lorem / TODO / TBD / XXX / TK | — |
| `hairline-strokes` | strokes < 0.1 pt may vanish in print | Make2D linework weights |
| `swatch-only-color` | a non-neutral fill used only in ≤ 6 small shapes, never stroked | raster images aren't scanned; if the keyed items are in a placed image, confirm by eye |
| `off-palette-fills` | fills > 0.5 in² not near any palette hex (grays and near-black ignored) | pass the palette the project actually uses |
| `changed-region` (INFO) | pixels changed vs. the previous export | every region should map to an intended edit |
| INDD `notAt100` | a placed drawing is scaled | the stated drawing scale must be recomputed |

## Eval

`tests/seeded_eval.py SHEET.pdf --work <scratch> --palette …` copies a real sheet and plants
five defects: a stray line, a legend swatch with no symbols, an off-palette fill, 3 pt text
and "TBD". It then runs the preflight with `--compare` and scores detection against that
answer key. The last run, on a real 36x24 review sheet (2026-10-05), caught 5/5. Re-run it after
any change to the script. Stray linework that existed before the first export is invisible
to `--compare`, so the visual pass stays mandatory.

Design critique (conventions, argument, composition) is a separate step, not covered here.
This skill is the evidence pass, and it runs before that critique.
