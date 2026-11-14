---
name: model-assembly-sheet
description: Make the paper that gets a physical architecture model assembled correctly — a 1:1 placement sheet (PDF printed at 100 %, with a 50 mm check bar) showing where every loose piece and post hole goes on the base, brass/wire post cut lengths that account for socket depth and how the parts actually seat, and a simple naming rule so each post finds its hole. Use when the user asks "where does this go", "how do I know which post is which", "brass lengths", "cut list for the posts/columns/rods", "placement guide", "template to glue the pieces", or is about to glue screens, furniture, trees or posts onto a site model or lot — even if they only paste a list of lengths.
---

# Model assembly sheet

Evidence base: one architecture studio project, Oct 6–7 2026. `garden-pieces-PLACEMENT-1to1.pdf` placed the garden screens, table set,
winter sun bench and downpipes, and labelled the 8 brass posts that hold the fin bridges on the plywood lot, with each
post's cut length. Script: `scripts/placement_sheet.py sheet.json` (spec format in its docstring). Run it with
`python -I` (environment in the repository README). Re-run on that project's data, it reproduced the eight cut
lengths exactly (the data is not included here).

## 1. Cut lengths: get the formula right before the saw comes out

`cut = height above the base top + socket depth + seating offset`
- **Height above the base**: from the model, measured from the base's top surface to the underside of what the post
  carries.
- **Socket depth**: how far the post goes into its hole. In that project it was one 3/16" plywood layer (4.8 mm), with the
  post standing on layer 2.
- **Seating offset**: any difference between how parts were designed to sit and how they actually sit. The walls were
  generated with a 1.0 mm plinth meant to sink into a pocket in a printed lot. The real lot was flat plywood, so every
  house, roof and bridge sits 1.0 mm higher, and every post needed +1.0 mm. Look for this whenever the base changed
  material or method after the parts were generated. It is the classic silent 1 mm error.
- Tolerance: ±0.3 mm is fine. Tell the user to stand each post so it just touches the part it carries, then glue it at
  the base. Cut with a hacksaw and miter box, and file the ends square.
- Sanity checks to give the user: longer spans or higher ends need longer posts. In that project, inner posts were taller than
  outer ones and the west bridge's posts taller than the east's. If a post looks wrong for its hole, it is probably
  swapped.

## 2. Names the user can read off the model

Build names from the model's own logic, in a fixed order: **zone letter** (A = street half, B = alley half),
**element number** (1 = west bridge, 2 = east bridge), and **position** (inner = near the middle path, outer = near the
lot edge). State the viewpoint ("stand at the alley end looking toward the street; west is on your left"), and give a
table laid out the way the holes appear from that viewpoint. Suggest a tape flag with the name on each post as it is
cut.

## 3. The 1:1 placement sheet

1. Collect the STLs that were actually printed, plus the frame shifts (`placements.json`, see `stl-fit-and-repair`).
   Pieces exported in the model frame (`..._MODEL-POSITION.stl`) need no shift.
2. Write `sheet.json`:
   - Outline each part with horizontal sections (`cuts_mm` above the part's own bottom): 4 mm through walls clears the
     plinth; 0.3 mm through furniture gives the legs; add seat and top heights for benches and tables.
   - Mark context-only parts (whole houses) with `"fit": false`, so the page centres on the pieces being placed.
   - Choose colours that tell the categories apart (grey walls, black screens, blue downpipes, brown furniture, red
     posts) and say so in a note.
   - Add orientation arrows named after real things ("STREET END (<street name>)"), not N/S, unless the north arrow is on
     the model.
3. Run `placement_sheet.py sheet.json`. Exit 1 means the drawing does not fit: use `"page_mm": [279.4, 431.8]`
   (tabloid) or split the sheet. It writes the PDF, a PNG preview and `<name>_post-cut-list.csv`. Look at the PNG
   before sending.
4. Instructions for the user: print at **100 % / actual size**, then measure the 50 mm check bar. Cut around the area,
   align it with two known features (house corners and post holes), prick each outline through onto the base with a pin,
   and glue along the pricks (thin CA or wood glue on the piece's base edge).

## 4. Before calling it done

- The lengths in the table, the CSV and the PDF labels all come from one calculation; never retype them by hand.
- Note on the sheet which assumptions the lengths include (socket depth, seating offset).
- If any piece changed after printing (for example a new bridge version), regenerate the sheet from the printed files
  and say which version it matches.
