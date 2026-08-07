# Lecture decks extract through mineru, and cannot chunk like books

The 192 files taken from the master archive go through the same extraction as
the forty-three books — `mineru`, `content_list.json`, the path ADR-0005 and
ADR-0006 already settled. They do **not** go through the same chunker. A slide
is roughly a fortieth of a book section, and the parent/child design that makes
retrieval readable depends on the parent being substantially larger than the
child.

## Considered Options

**PyMuPDF's text layer** was the tempting option: the whole corpus in nine
seconds against roughly an hour and three quarters for mineru, and no GPU. It
was measured on six decks stratified by text density, maths, figures, and
whether a text layer exists at all. It loses on three counts, any one of them
disqualifying:

- **It corrupts maths rather than missing it.** In `gp01-introtogp`, a Gaussian
  Processes deck, `E[Φw]` extracts as `E[!w]`: the symbol font maps to the
  wrong ASCII. Corrupted formulae are worse than absent ones, because nothing
  downstream can tell that they are wrong. mineru returned 42 equations from
  that deck, every one carrying LaTeX.
- **It cannot see a scan.** `fem-1d` yields 10 characters per page and 94% of
  its pages empty. mineru OCRs it to 576 characters per page and 72 equations.
- **It has no structure to chunk on.** mineru types headings, figures, tables,
  charts and code separately; PyMuPDF returns one undifferentiated string.

Two decks appear to favour PyMuPDF on raw character count — `dgm-03` at 464
against 402, `l5` at 341 against 282. They do not. mineru types the repeated
slide furniture as `header`, `footer` and `page_number`, which `assemble.py`
discards: 297 header blocks across 112 pages in the first, 45 headers and 42
page numbers across 44 pages in the second. The lower number is the clean one.

## Why the book chunker does not carry over

mineru returns almost exactly one heading per slide — 0.95, 1.05, 1.09 and 1.26
per page across the four PowerPoint-derived decks. The existing chunker splits
on headings, so each slide would become its own section. Measured against
`CHILD_TOKENS = 350` and `PARENT_TOKENS = 2000`, that is the problem:

| deck | median slide | as tokens |
| --- | --- | --- |
| `l5-graph-neural-networks` | 45 chars | ~11 |
| `dgm-03-efficient-attention` | 185 chars | ~46 |
| `14-unit-4-kubernetes` | 277 chars | ~69 |
| `gp01-introtogp` | 579 chars | ~144 |
| `riemanniana` | 1155 chars | ~288 |

A parent of 46 tokens is not a parent. Expanding a matched child to it returns
the child again, and the reader gets one slide with no argument around it —
precisely the failure the parent/child split exists to prevent. Slides
therefore chunk by *run*: consecutive slides accumulate into a parent, with the
slide as the child.

Where that run should end is not settled here, and deliberately so. Picking
2000 tokens because books use 2000 tokens would repeat the mistake this
document is about. It needs an evaluation set — questions per course with known
answers — measured against real retrieval before a number is chosen.

## Consequences

Two courses are flagged by the same measurements rather than discovered later:

- **IAG is nearly textless.** `l5-graph-neural-networks` carries 45 characters
  per slide against 46 extracted figures across 44 pages. The argument lives in
  the diagrams. Indexing its text will retrieve almost nothing useful, and
  saying so now is better than reporting the course as covered.
- **Scans have no heading structure.** `fem-1d` returns 0.18 headings per page
  where the PowerPoint decks return about 1.0. Chunking by run needs a
  page-based fallback where headings are absent.

Extraction cost is about 1.04 seconds per page, so 5,823 pages is roughly 1.7
hours on an RTX 3050 — measured over 330 pages, not estimated.
