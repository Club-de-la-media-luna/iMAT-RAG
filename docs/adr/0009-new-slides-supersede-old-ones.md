# ADR-0009: This year's slides supersede last year's, measured before they are trusted

Status: **accepted**, implemented (`imat_rag.supersession`, `imat_rag.refresh`, ranking in
`imat_rag.index.search`). Builds on `worktree-semester-intake` (`rag stage` / Moodle intake),
which is how this year's decks enter the corpus. Where the build departs from the draft, see
[As built](#as-built).

## Context

The corpus holds last year's lecture material (M9, `ARCHIVOS_MASTER`, 2025-26). During
2026-27 the lecturer publishes each chapter's deck before it is taught, and it is taken in
through the staging intake. Three things must hold:

1. **The new deck wins.** For the course actually being examined this year, this year's deck
   is the authority, above last year's version of the same deck.
2. **Nothing is erased.** Last year's deck stays in the corpus: material the lecturer cut may
   still be the clearest explanation of something, and an exam bank written against last
   year's deck still cites it. It is retrievable, just never ahead of its successor.
3. **"Is the new deck actually better?" is answered without spending tokens** whenever the
   answer is obvious, and with a compact, targeted report when it is not.

Nothing ranks on `source_tier` yet (`SourceTier` says so), and there is no notion of a
source's academic year, nor of one source replacing another.

## Measurement (2026-10-03, on the published index, read-only)

Child-chunk vectors already in LanceDB (BGE-M3, unit-normalised). For decks A, B: for every
child of A, its best cosine similarity to any child of B; *coverage* = share of children
whose best match is ≥ τ.

| Pair | A→B covered @0.85 | B→A covered @0.85 | mean best | Truth |
|---|---|---|---|---|
| MP `tema-2/parte1-incompleto` → `parte1` | 0.97 | 0.73 | 0.96 / 0.92 | draft → finished |
| MGP `t3/flujoscontinuos` → `flujoscontinuosii` | 1.00 | 0.61 | 1.00 / 0.90 | extended deck |
| MP `tema-2/parte1` → `parte2` | 0.00 | 0.00 | 0.69 / 0.68 | same chapter, other deck |
| MGP `t1/slides` → `t1/repaso` | 0.00 | 0.00 | 0.63 / 0.67 | same folder, other deck |
| MGP flows → MP `tema-2/parte1` | 0.00 | 0.00 | 0.54 / 0.55 | unrelated |

Versions of one deck cover ≥ 0.6 in both directions; different decks cover 0.00 in both, and
their mean best similarity never reaches 0.70. The gap is wide enough that matching and
grading can be done on vectors alone.

## Decision

### 1. Vintage and supersession are records, not index fields

- Every intake entry gains `"year": "2026-27"` (absent = `"2025-26"`, the M9 drop).
- A new record, `supersessions.json` beside `intake.json` (in git, small):

  ```json
  {"supersessions": [{
     "successor": "mgp-slides-t3-flows-t3-flujoscontinuos",
     "predecessors": ["mgp-slides-t3-flow-models-t3-flujoscontinuos"],
     "grade": "revised", "added": 0.12, "dropped": 0.03,
     "measured": {"tau": 0.85, "model": "BAAI/bge-m3", "successor_children": 41,
                  "predecessor_children": 38},
     "decided": "auto" }]}
  ```

Ranking reads the record at query time, so accepting or reverting a supersession never
re-embeds anything and never rewrites a chunk (ADR-0003: chunk ids stay content-addressed).

### 2. The pipeline: `rag refresh <slug>` (or every unmatched 2026-27 deck)

Stages, cheapest first; a stage that settles the question stops the pipeline.

1. **Bytes** — the source SHA-256 equals an existing source's: duplicate, nothing to do
   (already refused by the intake).
2. **Text** — normalised chunk text hashes (whitespace/case-folded child text) identical to a
   predecessor's: grade `same`. No vectors needed.
3. **Vectors** — extract and chunk the new deck as usual (mineru; GPU, no tokens), embed its
   children only (seconds), then:
   - **Find predecessors**: every 2025-26 deck *of the same course* whose children cover the
     new deck at ≥ 0.30 @τ=0.85 is a predecessor candidate. Topic folder names are a
     tie-break only — they change between years (`t3-flow-models` vs `tema-3`), and one old
     deck may be split into two new ones or two merged into one (many-to-many is allowed).
   - **Grade** with `added` = 1 − (new covered by predecessors) and `dropped` = 1 − (predecessors
     covered by new):

     | Grade | Rule | Action |
     |---|---|---|
     | `same` | added ≤ 0.05 and dropped ≤ 0.05 | supersede, no report |
     | `revised` | added ≤ 0.30 and dropped ≤ 0.30 | supersede, short report (counts + breadcrumbs) |
     | `changed` | otherwise, with a predecessor | supersede, **diagnose** |
     | `new` | no predecessor | nothing to supersede; record as new material |

     Thresholds are named constants, to be revisited once ten real chapters have gone through.
4. **Diagnose** (only `changed`, and `revised` on request) — still no LLM:
   - *Added*: new children with no match ≥ τ, grouped by breadcrumb and page range.
   - *Dropped*: predecessor children with no match ≥ τ, grouped likewise.
   - *Moved*: matched pairs whose order differs (Kendall rank correlation over matched
     positions). Coverage is order-blind, so reordering never moves `added`/`dropped`; this
     group only tells the reader that slides were reshuffled, not rewritten.
   - *Kind of change* from `content_types` of added/dropped chunks (equations, tables, code,
     figures): "added 6 slides with equations under 3.2 Normalising flows".
   Written to `derived/refresh/<successor>.md`: one line per group with page anchors, plus
   the first ~200 characters of each unmatched child. That file is what an agent reads when a
   judgement is needed ("are the new slides better?") — it is a few hundred tokens instead of
   two decks, and ADR-0002 stands: the pipeline measures, the agent judges.
5. **Record** the supersession (`decided: auto`, or `review` for `changed` until a human/agent
   confirms with `rag refresh --accept/--reject <slug>`). Re-index the new deck's children
   (append; no full rebuild).

### 3. Ranking: successors first, predecessors kept

`search` over-fetches (2×limit), then before expansion:

- A hit whose source is a **predecessor** is multiplied by a demotion factor (0.6) on its fused
  score.
- If a predecessor's child matches (≥ τ) a successor child that is also in the result set, the
  predecessor hit is dropped as a duplicate — the successor says the same thing, newer. This
  compares child vectors at query time: they are read back from LanceDB for the over-fetched
  hits only (≤ 2×limit rows, no extra embedding).
- Predecessor material the successor **dropped** stays reachable: when it is the only thing
  that answers, it is still returned, flagged.
- `Hit` gains `vintage: str` and `superseded_by: str | None`, so the citation reads
  "MGP T3 Flujos continuos (2025-26, superseded by 2026-27), pp. 12–14" and the agent can say
  so instead of presenting cut material as current.
- `coverage()` reports per course how many chapters are on 2026-27 material.

`reject` marks the record line `rejected`; ranking ignores it and the old deck is back on top
with no rebuild.

## Consequences

- Zero tokens for the common case (same or lightly revised deck); one small report per deck
  that genuinely changed.
- Extraction (mineru) remains the expensive step; it was needed anyway to make the new deck
  searchable.
- Ranking now depends on a record outside the index; `manifest.json` must hash
  `supersessions.json` too, or "why did retrieval change?" loses its answer.
- First use of `source_tier`-adjacent ranking; a later ADR can add the tier ladder through the
  same post-fusion step.

## As built

Where the implementation settled what the draft left open, or departs from it:

- **`reject` keeps the line**, marked `"decided": "rejected"`, rather than removing it.
  Ranking ignores it just as if it were absent, so no rebuild is needed. Deleting it would have made the
  next bulk `rag refresh` propose the same supersession again.
- **`decided` values**: `auto` (`same`, `revised`, `new`), `review` (`changed`), `accepted`,
  `rejected`. `review` records already rank. A `changed` deck supersedes, as the grade table
  says; review decides whether it stays.
- **`new` is recorded too**, with no predecessors, so the deck counts as having a verdict and bulk
  refresh does not measure it again. It supersedes nothing.
- **Candidates** are intake sources of the same course *and kind* with an earlier vintage.
  Bulk refresh (`rag refresh` with no slug) only takes `slides`. An exam is not a version of last
  year's exam, however many problems it reuses. A named slug of any kind can still be refreshed.
- **Year** is written by `rag take` (`--year`, default the current course year, checked against
  `YYYY-YY` because vintages are compared as strings). `rag inbox` writes none: a contributor's
  drop does not say when it was taught, and an absent year already means 2025-26.
- **Vectors**: the predecessors' come from the index. The successor's come from the index if
  it is already there, and are otherwise embedded once and reused for the append. The encoder loads
  only if something is missing.
- **Successor not chunked yet**: `rag refresh` chunks it from its extracted Markdown. It does
  not extract (mineru is a separate, GPU-bound step). A deck with no extraction is refused with the
  `rag extract` command to run.
- **Kind of change** is read from block prefixes (`$$`, `|`, `<table`, `` ``` ``, `![`).
  `content_types` only distinguishes atomic from prose.
- **Moved** lists the fewest successor children whose removal leaves the rest in the
  predecessors' order (a longest non-decreasing subsequence), plus Kendall's rank correlation.
- **Hit** carries `vintage`, `superseded_by` (successor slug(s)) and `superseded_in` (successor
  vintage, for the citation). Ledger books have an empty vintage.
- **`coverage()`** reports `by_year` (intake sources per vintage) and `superseded` per course.
- **The manifest** stores `supersessions_sha256`. Every manifest write stamps it, and
  `refresh`/`accept`/`reject` restamp it.

## Tests to write first

- Grading on synthetic decks: identical, one slide added, half replaced, reordered only,
  unrelated (unit vectors built by hand — no model download).
- Predecessor matching is per course, many-to-many, and ignores topic names.
- `search` with a record: successor outranks its predecessor; the predecessor's unique chunk
  is still returned when it is the only match, flagged; removing the record restores the old
  order.
- Calibration fixture: the five pairs above, B as successor and A as candidate predecessor,
  expected grades `revised` (added 0.27, dropped 0.03), `changed` (added 0.39, dropped 0.00 —
  the extended deck adds enough to deserve a diagnosis), `new`, `new`, `new`.
