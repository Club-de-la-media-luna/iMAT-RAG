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

## The run is 800 tokens, and no evaluation set was needed

This document first said the run length needed an evaluation set measured
against real retrieval before a number could be chosen. That was wrong, and
the reason is worth writing down because it is easy to get backwards.

**Run length does not change what matches.** The index only ever compares
children, and a child is one slide whatever the run is set to. Changing the
run changes which parent a matched child expands to — how much argument comes
back around the hit — and nothing else. Recall is invariant to it. An
evaluation set would have measured a number that cannot move, and picking 800
because a sweep "showed" it would have been a fabricated result.

What the choice actually trades off is readability, and that is measurable
directly. Across the first forty sources extracted, at 800 tokens:

| | |
| --- | --- |
| median parent | 740 tokens |
| median child | 106 tokens |
| ratio | about 7× |

Seven times is the point. A parent has to be substantially larger than the
child that found it or expansion returns the child again. On DRL Tema 5 — 51
sections, 5,542 tokens for the whole deck — 800 gathers about six sections,
which is one argument, while the book setting of 2000 would have made each
parent a third of the deck.

It remains a parameter. What would justify moving it is a reader finding the
returned span too thin or too bloated, which is a judgement about prose, not a
score.

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
