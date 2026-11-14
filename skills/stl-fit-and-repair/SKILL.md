---
name: stl-fit-and-repair
description: Turn architecture-model geometry into STLs that print as ONE clean solid and fit the parts already printed — weld parts that only touch, drop loose crumbs, thicken paper-thin fins/leaves, fuse open render meshes (cars, scanned figures), repair downloads until Bambu Studio shows zero open/non-manifold edges, cut a new part 0.15 mm clear of printed mates and prove it drops on, and design supports out (no top rails, flush sides, tie hanging ends). Use whenever the user says a print is "detached", "not one piece", "thin at connections", "has weird lines", "make sure it fits on the walls/roof/base", "Bambu says open edges / non-manifold", "repair this STL/model", "supports touch the railing", or needs any part pulled out of a saved .3dm for printing — even if they only send a slicer screenshot.
---

# STL fit and repair

Evidence base: one architecture studio project's massing (1/8") and chunk (1/4") models, Oct 2026 — one-piece welded roofs cut to the
printed walls, fin bridges printed on their side, garden screens, v22 picket railings, a Mini, a voxel-fused Ford
Focus, scanned 1:50 people. Scripts are in `scripts/`; run them with a Python that has the repository's
`requirements-arch-tools.txt` installed (trimesh, manifold3d, pymeshfix, scipy, scikit-image). STL units are mm.

## Workflow

1. **Get the geometry from a saved file, never the live Rhino doc.**
   `scripts/rhino_extract.py MODEL.3dm --layer "PARENT::CHILD" [--name-contains X] --mmft 3.175 --out part.stl`
   prints the model SHA-256 (record it), skips hidden objects unless `--include-hidden` (alternate states such as
   open/closed fins are hidden but printed), and falls back to the convex hull of Brep vertices for objects saved
   without a render mesh — exact for flat plates and boxes, wrong for curved parts, so it lists every fallback.
   mm per model foot = 304.8 / scale denominator: 1/8" → 3.175, 1/4" → 6.35, 1:50 people at 1:48 → × 50/48.

2. **Make it one piece.** Separate closed meshes are not one printable body (v13 had 66, none unioned).
   - `meshkit.py weld IN OUT` — union + a weld bead along every seam where parts only touch (face or line contact);
     beads are hulls of both surfaces within 1.2 mm of the seam, in 3 mm segments. Tested: edge-only contact 2 → 1 body.
   - `meshkit.py drop-fragments IN OUT --min 2.0` — delete loose bodies under 2 mm³. **Do not tie crumbs on with
     struts:** the walls got stray bars from auto-struts, the slicer supported them, and the user had them removed.
   - Pieces built to touch exactly (pickets against a slab face) come out NotManifold with inconsistent winding.
     Grow each piece 0.05–0.1 mm per side (oriented box or `meshkit.grow`) so contacts overlap and fuse.

3. **Hold minimum features.** Walls ≥ 0.6 mm; fins/bridge plates ≥ 1.2 mm (0.7 mm snapped during support removal);
   leaves: `meshkit.py thicken IN OUT --grow 0.12` (1/4") or `0.14` (1/8") prints on a 0.2 nozzle — it prints the
   resulting thickness. Details too fine to print (0.3 mm bench slats) become one solid plank: say so in the reply.

4. **Fit to what was actually printed.**
   `scripts/fit_to_mates.py NEW.stl --mates PRINTED.stl [...] --placements placements.json --clear 0.15 --out NEW-FIT.stl`
   Use the STL files that went to the printer as mates, not a newer regeneration. It subtracts the mates grown by the
   clearance, drops crumbs, exports, and checks overlap = 0, drop-on path clear (raised 0.05–30 mm), one body,
   watertight. Exit 0 = PASS. Re-run on the project's pair-A roof: 0.0005 mm³ overlap, path clear, 1 body.
   `placements.json` maps each file stem to the [x, y, z] shift that moved it from model frame to print frame:
   write it whenever a generator re-centres parts onto the bed, or later fits are guesswork.

5. **Export safely and check.** Everything goes through `meshkit.clean_export` (inside every command): drops
   zero-volume bodies, removes collapsed/twin faces, seals edge pinches with 0.25 mm fillers, writes, **reloads
   from disk and re-checks** — float32 STL rounding turns valid solids into pinched ones. Then
   `meshkit.py check FILE...`: `bodies` must be 1 (zero-volume bits are reported separately and are harmless),
   `bad_edges` 0. Also run `physical-model-prep/scripts/check_mesh.py` for bed fit and thin-wall warnings.

6. **Look at it.** `scripts/render_views.py A.stl B.stl --out views.png [--zoom x0 y0 z0 x1 y1 z1]` and read the
   PNG before telling the user it is fixed. Automated hanging-face tests gave sliver noise on real railings; a zoomed
   render answered "do the pickets drop past the slab?" Send the render with the answer.

7. **Write new files, keep the old.** Never overwrite a file the user already printed or is printing; give the new
   one a self-describing name (`pair-A-walls_v22-PICKETS-PAST-SLAB_no-top-rail.stl`) and move replaced versions to
   `_superseded/<date>-<what>/`. If a generator writes every part next to itself, run it in a scratch folder.

## Design the supports out (the user's corrections)

Supports that touch delicate parts snap them; settings alone did not stop it (`bambu-print-recipes`). Change geometry:
- **Remove what needs support** if the read survives: the top rail over the pickets needed support; the user: "get rid of
  that, I like the horizontal read anyway".
- **Tie hanging ends back:** picket ends dropping 1.6 mm past the slab hung over a ~0.5 mm air gap; a small web behind
  each end fused all 178 to the wall, so the drop reads from the front and prints unsupported.
- **Flush sides for parts printed on their side:** post tabs stuck out of the bridge's bed face ("I want it to be a
  flush side so it's on the plate"); remove them and glue the posts against the edge instead. Trim with manifold
  `trim_by_plane(normal, offset)` (keeps `normal·x ≥ offset`); trimesh `slice_mesh_plane` failed on the EAST bridge.
  When picking the face band to trim, use only faces within 0.6 mm of the extreme, or the band's inside face is
  taken as outside and the whole band is cut.
- **Orient for the bed**, not for the model: bridges on their flat side, furniture upside down (seat/top on the bed),
  screens upright, roofs seams-up, figures standing.

## Repairing downloads and render meshes

- `meshkit.py repair IN OUT [--max-faces 80000]` — pymeshfix, inside-out bodies flipped (negative volume), manifold
  rebuild, centred on z = 0. Fixed the Mini and every scanned person/pet to zero bad edges.
- Open multi-shell render meshes (the Ford Focus: 15 open shells, open underside) → `meshkit.py solidify IN OUT
  --pitch 0.07`: voxel 5-of-6-axis vote, fill, open, largest body, marching cubes, Taubin smoothing (no terracing),
  pymeshfix. Expect minutes, not seconds, for a 45 mm car. pymeshfix alone cannot close shells that interpenetrate.
- Keep files phone-sendable: decimate to ≤ 60k faces per figure / ~120k per car; a 30 MB STL did not reach the phone.

## Gotchas already paid for

- **pymeshfix keeps only one connected component per call.** On a 16-leaf agave it returned one leaf, and the
  checks still said "1 body, 0 bad edges". `meshkit.repair` now fixes each component separately; if you call
  pymeshfix yourself, split first. This is also why step 6 (look at the render) is not optional.
- `ValueError: string is not a file` from trimesh = wrong path (check `_superseded/` and the scratch run folder).
- `Not all meshes are volumes` in a union = a flat hull; skip hulls under 0.01 mm³; seed surface sampling (seed=5).
- A helper named `inspect.py` (or `json.py`, `csv.py`) shadows the stdlib and breaks imports — name scripts by purpose.
- Weld/fit runs on 200k-face roofs take seconds; voxel solidify and triangle-prism thickening take minutes: say so.
- Run Python that reads downloaded files with `-I` from a different directory than the downloads.

## Reply format

Lead with the file to print and what changed, then the checks as numbers (bodies, bad edges, overlap, drop-on path),
then the render. Keep status words distinct: generated → checked → rendered → printed → fitted. Only the user can
confirm printed/fitted.
