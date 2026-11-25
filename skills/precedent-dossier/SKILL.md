---
name: precedent-dossier
description: Research architectural precedents into a cited dossier with a source ledger, so no claim (architect, year, client, program, dimension, intent) reaches a crit without a source id. Sets up the folder, assigns stable S### ids at time of access, ranks sources by class (architect, permit/public record, publication, builder, listing/marketing, social), separates architect-stated intent from inference, records contradictions instead of resolving them silently, tracks drawings and saved images with provenance, and validates the ledger with scripts/check_ledger.py. Use for "precedent research", "find precedents", "case studies", "research this building", "sources for", "who designed", "dossier", or any request to find drawings, intent, or facts about an existing building.
---

# Precedent dossier

Modeled on a real studio research dossier (four houses, three parallel lanes, 69-source
ledger) and that project's facts sheet. Rule zero: **cite or don't claim.**

## 1. Folder layout

```
<project>/research/YYYY-MM-DD-<topic>/
  README.md            start here: identity table (spoken target -> resolved project ->
                       architect -> confidence + source ids), read order, known gaps
  RESEARCH-BRIEF.md    the ask as given, targets verbatim, lanes + id blocks, permissions
  SOURCES.csv          the ledger. One row per URL. Primary agent owns it.
  agents/NN-slug.md    one note per precedent (or tight pair), from templates/precedent-note.md
  DRAWINGS.md          D## index: type, local file, source id + page, scale, limits
  ASSET-INVENTORY.json every saved file: path, kind, source_id, url, bytes, sha256
  SYNTHESIS.md         transferable moves -> proposed tests for our project (inference, labelled)
  VERIFICATION.json    checks run, results, limits, file hashes
  NEXT-AGENT.md        ten-line primer for whoever resumes
  assets/  evidence/   saved PDFs/images (assets) and page captures/records (evidence),
                       prefixed by lane: 00- primary, 01-, 02-, ...
```

Optional: `ACCESS.md` when records took real work to get (portal, API, request form, what
failed). The original dossier called this `PUBLIC-RECORDS-AND-DRAWING-ACCESS.md`.

## 2. Source classes and weight

Use these `source_class` values (the first six come from the original ledger):

| source_class | Authoritative for | Not evidence for |
|---|---|---|
| `architect project source` | credit, project name, published drawings, architect's stated intent | as-built state, exact areas (often rounded) |
| `official civic / planning record` | legal address/parcel, permitted program, architect/engineer of record, permit dates, **written** dims on scanned plans | design intent; current condition |
| `architect firm source` | firm-general philosophy | this project's intent (applying it = inference) |
| `project builder source` | credit, completion year, program as built | architect's intent |
| `publication / corroboration` | architect quotes inside interviews; second source for credits | editorial attributions on their own (the original dossier: a broker editorial misattributed one house) |
| `listing / property corroboration` | address, photos, marketing areas | authorship, intent, scale (listing plans lacked title blocks) |
| `developer / marketing` | client/developer identity, unit mix as sold | architect intent, verified areas |
| `book / academic` | analysis, historical context, published drawings with scale | current state |
| `social / user-posted` | a lead to follow | anything, until a stronger source confirms it |

When sources disagree, the higher class usually wins **for its own column only**: a permit
beats a listing on legal program; the architect beats the permit on intent.

## 3. Citation rules

- **Ledger first.** Add the row to `SOURCES.csv` when you open the source, not afterwards.
  Ids are `S###`, assigned once, never renumbered. Do not generate ids by sorting URLs; that
  renumbers everything when a source is added.
- **Every factual claim carries an id on the same line:** `[S012]`, `[S012 p.73]`,
  `[S012 fig.4; S020 p.3]`. Pinpoints (page, sheet, figure, timestamp) go in the citation,
  never in the ledger label, because one URL is one row however many pages you cite.
- A claim with no source is marked `[unsourced]` or deleted. Never in a crit deck.
- **Attributions** (architect, year, client, architect of record) need a
  `architect project source` or `official civic / planning record`, or two independent
  sources from other classes. Republished press repeating one release counts once.
- **Dimensions** come only from a drawing or record that writes the number or states a
  scale: `[S021 p.3, written]` or `[S021 p.3, scaled 1/8"=1'-0"]`. Never from a photo,
  render, or image proportions. Published areas are "published figures", not measurements.
  Our own derived numbers say `[derived: method]` and cite their ledgered inputs on the same
  line (facts-sheet pattern). In a Dimensions table, the source + pinpoint and method may
  be in separate cells of the same row. Label reported values explicitly as `published figure`
  (with a source); `reported` alone does not distinguish a figure from a measurement.
- **Intent layers stay separate:** architect-stated / team- or client-stated / firm-general
  / observed in photos / our inference. Label which layer each move belongs to.
- Status words from the project's evidence vocabulary: `verified-file`, `verified-live`,
  `reported`, `inference`, `rejected`. Search snippets and blocked pages are `reported`,
  never `verified`.
- `qualification` is specific to that source ("permit names architect of record, not
  designer"; "plans cropped, no title block"). Never boilerplate like "see report".
- `access_date_local` is the day that source was actually opened.

## 4. Parallel research (what the original dossier did)

It ran three fresh-context agents, one lane each, while the primary integrated:

- Each lane owns `agents/NN-slug.md` and assets/evidence prefixed `NN-`. Lanes never edit
  README, SYNTHESIS, SOURCES.csv, or project handoff files.
- Give each lane an id block so parallel ids never collide: primary `S001-S099`, lane 01
  `S100-S199`, lane 02 `S200-S299`. Lanes put their rows in a `## Sources` table at the
  bottom of their note with the ledger's columns.
- The primary merges those rows into `SOURCES.csv`. If two lanes ledgered the same URL,
  keep the lower id and replace the other in the notes. Then it checks the key evidence
  itself (opens the permit, looks at the plan) and writes README, SYNTHESIS, DRAWINGS.
- One precedent? Skip the lanes and write `agents/01-slug.md` yourself.

## 5. Copyright and assets

- Store links, short attributed quotes (a sentence at most) and your own paraphrase. Never
  paste long passages or whole articles.
- Save images/PDFs locally only as **private study references**: record path, source id,
  URL, access date, sha256 in `ASSET-INVENTORY.json`. Claim no publication licence.
- No login or paywall bypass, no buying documents, no contacting architects or owners
  unless the user says so. A blocked page is recorded as blocked.
- Never substitute AI-generated or redrawn drawings for source drawings. Redraws are ours,
  labelled as such, and cite the sheet they trace.

## 6. Contradictions

Every note has a `## Contradictions` section. Record both sides with ids, which one you
prefer and why (class, date, specificity), or "unresolved". Rejected claims go in
`## Do not reintroduce` so the next agent doesn't revive them (the original dossier: a wrong
firm credit and a predecessor address). Area/program figures that drift across permit, approval and
listing stay listed side by side; never average them into one "verified" number.

## 7. Validate

```bash
python3 scripts/check_ledger.py <dossier> --strict-dimensions   # from this skill's folder
```

Exit 1 = hard errors (bad/missing columns, duplicate or malformed ids, bad URLs, empty
required fields, notes citing ids that aren't in the ledger, asset-inventory errors below) or, with `--strict-dimensions`,
missing/incomplete dimension provenance. Without that flag, dimension findings are warnings
and do not change the exit code. Other warnings stay warnings in either mode: ledger rows
never cited, inline URLs not in the ledger, `[unsourced]` tags, boilerplate qualifications,
duplicate URLs.

`ASSET-INVENTORY.json` is a JSON array, one object per saved file:
`{"path": "assets/00-plan.pdf", "kind": "drawing", "source_id": "S001", "url": "<ledger url>", "bytes": 48213, "sha256": "<64 hex>"}`.
It is required once `assets/` or `evidence/` holds any file (dossiers with no saved files
need none). The checker fails on malformed JSON or records, unlisted or missing files,
duplicate paths, source ids not in the ledger, a `url` that differs from that id's ledger
URL, and wrong `bytes`/`sha256`. Paths must be dossier-relative; absolute, `..` and
symlinked paths are rejected before any file is opened, so nothing outside the dossier is read.

For each Markdown line/row with a number + unit, provide one of:
- **Written:** ledgered source, pinpoint, `written` (e.g. `[S021 p.3, written]`).
- **Scaled:** ledgered source, pinpoint, `scaled` and an explicit positive ratio or scale
  equation (e.g. `[S021 sheet A101, scaled 1:100]` or `scaled 1/8"=1'-0"`).
- **Derived:** a nonempty `[derived: method]` and ledgered input citations on that line/row.
- **Published figure:** explicitly label it `published figure` and cite a ledgered source;
  this is a reported value, not a measurement, so no measurement method/scale is required.

Pinpoints include `p.3`, `page 3`, `sheet A101`, `fig.4`, or `timestamp 01:34`.
Markdown links to ledger URLs still count as citations; put the pinpoint in the link label
or beside it (`[plan p.3](ledger-url), written`). A ledger URL's `#page=3` also supplies a
page pinpoint. Source and method may be in separate cells of the same table row.

This is a line-based structural check, not source verification or a Markdown/units parser.
It cannot verify method correctness, source authority, or match each input to a calculation;
keep one claim per line/row and inspect the cited evidence. JSON receives citation checks
only; fenced examples are skipped. Offline regressions: `python3 -m unittest discover -s tests -v`.

## Done means

- [ ] README identity table: every architect/year/client cell has ids and a confidence word
- [ ] `check_ledger.py --strict-dimensions` exits 0; remaining warnings fixed or explained in VERIFICATION
- [ ] Measured dimensions have source + pinpoint and `written` or `scaled` + scale; derived
      values have method + ledgered inputs; published figures are labelled and sourced
- [ ] Each note: intent layers separated, `## Contradictions`, `## Do not reintroduce`, search audit
- [ ] Every saved file is in ASSET-INVENTORY.json with source id and sha256
- [ ] DRAWINGS.md says what was **not** found (no sections? say so) and the best next access route
- [ ] SYNTHESIS proposes tests, labelled inference; nothing claimed as adopted design
- [ ] NEXT-AGENT.md written; open questions listed, not smoothed over
