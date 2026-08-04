# v1 indexes basic-tier books only, behind an ordinal source-tier ladder

Every chunk carries an ordinal `source_tier` — `slides > exams > guide >
basic_book > extra_book`. v1 indexes `basic_book` only: 21 books, 11,990 pages,
601 MB, classified directly from the `Bibliografía Básica` /
`Bibliografía Complementaria` sections already recorded in each Course's ledger.

## Considered Options

Indexing the whole acquired corpus (41 books, 19,225 pages) was the default.
Restricting to basic tier removes 38% of pages, and removes the hard pages
disproportionately: four of the five scanned, no-text-layer books are
complementary reading, so the OCR burden falls from 2,578 to 979 pages. Both
known-broken downloads — truncated front-matter PDFs incorrectly marked as
acquired in the ledgers — are also complementary, so v1 never encounters them.

## Consequences

Because the tier is an ordinal field rather than a corpus boundary, adding the
complementary tier later is an append, not a re-ingest. The same field is how
lecture slides will outrank textbooks once they arrive — the ladder exists so
that "what the professor actually taught" beats "what the textbook says"
without special-casing.

Coverage of the basic bibliography is roughly 31% (23 acquired, 41 not found,
8 link-only, 2 pending) and is uneven: `EE` has no material at all and `IAG`
has one book. The system therefore reports its own coverage per Course rather
than answering from adjacent material.
