# NN — <Project name>, <address / city>

Lane NN · ids S<N>00–S<N>99 · researched YYYY-MM-DD · status: draft | integrated

Every factual line ends with its source ids: `[S101]`, `[S101 p.3]`, `[S101; S120 fig.2]`.
No id → `[unsourced]` or delete it.

## Identity

| Field | Value | Sources | Status |
|---|---|---|---|
| Name(s) | | | verified-file / reported / ⚠ conflict |
| Address / parcel | | | |
| Architect (design) | | needs architect/record source or 2 independent | |
| Architect of record | | | |
| Client / developer | | | |
| Year (permit / completion) | | | |
| Program / units / area | published figure, not a measurement | | |

## Intent (keep the layers apart)

- Architect-stated: "<short quote, one sentence max>" [S1xx p.?]
- Team / client-stated:
- Firm-general (not specific to this project):

## Spatial and material moves

1. <move> — <evidence> [S1xx] — drawn / observed / inferred

## Drawings found

| D## | Type | Local file | Source + sheet | Scale | Limits |
|---|---|---|---|---|---|
| D01 | plot plan | `assets/NN-...pdf` | [S1xx p.3] | written dims only | scan degraded |

Not found: <sections? elevations? details? say so>.

## Dimensions (measured, derived, or explicitly reported)

One claim per row. Keep the source + pinpoint and method on that same row, even when
in separate cells. Choose a provenance form:
- Measured: `[S1xx p.3]` + `written`, or `[S1xx sheet A101]` + `scaled 1:100`.
- Derived: ledgered input citations + `[derived: length times width]` (state the actual method).
- Reported: source citation + `published figure, not a measurement` (no measurement implied).

| What | Value | Source + sheet / ledgered inputs | Written / scaled (scale) / derived method / published figure |
|---|---|---|---|

Acceptance check: run `python3 scripts/check_ledger.py <dossier> --strict-dimensions`
from the skill folder. Fix incomplete provenance; do not add a marker unless the cited
evidence supports it. Record explanations for remaining warnings in VERIFICATION.

## Inferences for our project (not facts)

- <inference> — because <sourced move above>.

## Contradictions

- <claim A> [S1xx] vs <claim B> [S1yy] → prefer A because <class / date / specificity> | unresolved.

## Do not reintroduce

- <rejected claim> — rejected against [S1xx].

## Search audit

Tried: <queries, portals, archives>. Blocked: <url, HTTP status>. Best next route: <...>.

## Sources (lane rows; primary merges into SOURCES.csv)

| source_id | url | label | access_date_local | source_class | qualification | evidence_route |
|---|---|---|---|---|---|---|
