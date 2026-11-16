---
name: sun-study
description: Headless sun-path and direct-sun-hours analysis from a script, no Rhino or Grasshopper GUI and no Rhino MCP. Ladybug Tools computes sun positions for a site (lat/lon/tz, an EPW, or the los-angeles-ca preset), and trimesh/Embree casts rays from an analysis grid toward the sun through context geometry (.3dm, .stl, .obj, .ply). Outputs per-point hours as CSV, a JSON summary and a plan heatmap PNG. It can also print a sun altitude/azimuth table. Use when asked about "sun hours", "direct sun hours", "shadow study", "winter sun", "solar access", "sun path", "how much sun does the courtyard get", "is this space shaded on Dec 21", or for a numeric check of a massing's sun exposure. Direct sun only: not for daylight factor, sDA/ASE, illuminance or glare, which need a diffuse-sky daylight simulation.
---

# sun-study

Gives numbers for direct sun only. It does not make design judgements. Report the numbers and their limits, and let the user draw conclusions.

## Run
```bash
PY=python   # a Python with the repository's requirements-arch-tools.txt installed
S=scripts/sun_study.py   # run from this skill's folder

# Sun position table (no geometry needed)
$PY $S --site los-angeles-ca --date 12-21 --hours 7-17 --step-min 30 --sunpath-only [--out DIR]

# Direct sun hours on a rectangle (grid coordinates in MODEL units)
$PY $S --site los-angeles-ca --date 12-21 --hours 8-16 --step-min 15 \
  --geometry model.3dm --layers "01 WALLS" "04 ROOFS" \
  --grid-rect X0 Y0 X1 Y1 --grid-z 0 --spacing 2 --threshold 2 --out /tmp/sun_dec21

# Grid from closed curves (or meshed surfaces) on a .3dm layer, over a period
$PY $S --lat 34.05 --lon -118.25 --tz -8 --start 12-01 --end 02-28 --hours 9-15 \
  --geometry model.3dm --grid-from-layer "COURTYARD GRID" --spacing 1 --out DIR
```
Tests (from this skill's folder): `$PY -m pytest tests -q`

## Inputs
- **Location**: pick one of `--site los-angeles-ca` (34.052, -118.244, UTC-8), `--epw file.epw` (only its location is used), or `--lat --lon --tz`. `--tz` is the **standard-time** offset. There is no DST, so clock times are local standard time (PDT 13:00 = 12:00 here).
- **North**: `--north DEG` uses the Ladybug convention, north rotated counter-clockwise from +Y. The default 0 means +Y is north.
- **Period**: `--date MM-DD`, or `--start MM-DD --end MM-DD` (inclusive; a range like 11-01 to 02-28 wraps across New Year). `--hours 8-16` is a clock window and defaults to 0-24. `--step-min` defaults to 15 and must divide that window exactly (otherwise the command refuses the input). Each timestep is the **midpoint** of its interval. Sun below the horizon is skipped.
- **Geometry**:
  - `.3dm` uses the render meshes Rhino stored for Breps, Extrusions and Meshes. Block instances are expanded with their transforms; members on off layers are skipped like top-level objects (and counted in the off-layer warning) unless `--include-off-layers` is given.
  - Hidden objects and objects on layers saved as off are skipped by default; `--include-off-layers` adds the off layers.
  - `--layers` keeps only objects whose layer full path contains any of the given substrings (case-insensitive).
  - Curves, text and points never cast shadow.
  - `.stl/.obj/.ply` are read with trimesh. Give `--units mm|cm|m|in|ft`; the default is meters.
- **Grid**: `--grid-rect` places cell-centred points at `--spacing`, with `--grid-z` as the elevation (default 0). `--grid-from-layer` uses closed curves (points inside, curve z or `--grid-z`) or meshed surfaces (points dropped onto the surface). Grid values are in model units.

## Units
Everything is converted to **meters** from the .3dm `ModelUnitSystem` (mm, cm, m, in, ft and others) or from `--units`. CSV coordinates and the heatmap are in meters. `summary.json → units.model_to_meters` gives the factor back to model units. The ray origin is lifted by `--offset` meters (default 0.01) so a point does not hit its own floor.

## Outputs (`--out DIR`)
- `sun_hours.csv`: `x,y,z,hours` in meters. `hours` is the **total** for the period, so a multi-day run sums the days.
- `summary.json` contains:
  - location, period, timestep, daylight timesteps, max possible hours
  - grid count and spacing
  - `hours_total` and `hours_per_day_mean` (min/mean/max)
  - `pct_points_at_or_above_threshold` (per day; mean per day for multi-day runs)
  - unit info, geometry stats (objects total/considered/meshed/no-mesh/hidden/off-layer, block instances, triangles, bounds), and warnings
- `sun_hours.png`: plan heatmap with a colorbar. It shows totals for the period and draws a triangle outline only for meshes of 200k triangles or fewer.
- Stdout prints a short JSON digest. With `--sunpath-only`, stdout is a date/time/altitude/azimuth table (azimuth clockwise from north), and `sunpath.csv` is also written if `--out` is given.

## Reading results
- Compare against `max_possible_hours_per_day_mean`. That is the open-sky value for the chosen window, not 24 h.
- Points **inside** solid geometry, or under a roof, read 0. Mask them out, or place the grid only on open ground.
- Always read `warnings`. Objects with no stored render mesh are dropped, so a "sunny" result may be missing geometry. Re-save from Rhino after shading the model, or run ExtractRenderMesh.
- State the date, window, timestep and layer filter alongside any number you quote.

## Limitations
- **Direct sun only.** It computes no diffuse, reflected, radiation, daylight factor, sDA or UDI. honeybee-radiance and Radiance are **not installed**.
- **Geometry**:
  - It needs mesh geometry. NURBS without a stored render mesh, SubD without a mesh, and Surface objects without a Brep wrapper are ignored and counted.
  - Glass is opaque: every mesh blocks sun.
  - Terrain and neighbours count only if they are in the model.
- **Sun model**: sun positions are geometric from Ladybug, with no weather or cloud. An EPW sets the location only; its radiation data is not used.
- **Scale**: Embree ray casting is fast. Sanity run: 1.3M triangles × 14k points × 992 sun positions took about 1.3 s. A .3dm with millions of triangles loads in a few seconds. Plot memory is the practical limit.

## Environment
Install the repository's `requirements-arch-tools.txt` (ladybug-core, ladybug-geometry, trimesh + embreex and rtree, rhino3dm, numpy, shapely, matplotlib, pytest).
