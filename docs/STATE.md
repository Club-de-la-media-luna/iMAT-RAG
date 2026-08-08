# Where things stand

Resume point for the next session. Read [CONTEXT.md](../CONTEXT.md) for
vocabulary, [design.md](./design.md) for the shape, [adr/](./adr/) for why.

Last updated after M9. Every milestone in the build order is done.

## Done: M0 – M9

The system works end to end, from the CLI and over MCP. `rag search` and the
`search` tool return the same correctly cited passages — now from the lecture
material as well as the reading list, for all nine courses.

| | |
| --- | --- |
| Corpus | 211 sources: 21 books and 190 decks, exams, assignments and notes |
| | 17,813 pages, 1.9 GB of PDFs |
| Extracted | 190 staged sources extracted, 0 failures |
| Chunked | 47,472 chunks — 12,073 parents, 35,399 children |
| Indexed | 35,399 children embedded with BGE-M3, 212 MB LanceDB, 2 tables |
| Published | 10,043 files on the Hub, private, revision `8e9980a1` |
| Tests | 254 passing, lint 10.00/10 |

Coverage, per course, after M9:

| Course | Sources | Chunks | What it holds |
| --- | --- | --- | --- |
| DRL | 14 | 4,276 | 2 books, 9 decks, 3 notes |
| EE | 18 | 1,349 | 13 decks, 4 exams, 1 assignment |
| GI | 20 | 2,331 | 2 books, 6 decks, 9 exams, 2 notes, 1 assignment |
| IAG | 17 | 1,170 | 1 book, 16 decks |
| IAP | 25 | 17,685 | 4 books, 21 decks |
| IM | 35 | 5,632 | 5 books, 14 decks, 15 assignments, 1 notes |
| MD | 33 | 6,554 | 4 books, 27 decks, 1 assignment, 1 notes |
| MGP | 31 | 13,018 | 3 books, 24 decks, 3 exams, 1 notes |
| MP | 20 | 4,675 | 2 books, 14 decks, 3 exams, 1 notes |

**EE had no material at all before M9.** It now answers.

Three results that closed open risks:

- **Cross-lingual retrieval works.** `¿qué es la divergencia de
  Kullback-Leibler?` returns Murphy vol. 2 §2.7.1.1 — Spanish query, English
  book, no translation step.
- **OCR'd mathematics is retrievable.** `what is a Riemannian metric on a
  manifold` returns do Carmo ch. 2, pp. 52–54, from a scanned PDF with no text
  layer. GI and MD are not write-offs.
- **The MCP server answers over real stdio.** Verified with an actual client:
  handshake, three tools listed, `coverage` reporting `EE` as the one course
  with no material. `fetch` costs 0.05 s on the real 39k-chunk corpus.

## M9: the lecture material

A colleague's `ARCHIVOS_MASTER` drop — 217 PDFs, 912 MB — filed into the tree
the pipeline reads, and made searchable. 192 survived: 23 were byte-identical
copies of each other, one was a cluster user guide, and two were replaced by
the Markdown they had been printed from.

Material is filed at `courses/<CODE>/raw/<kind>/<topic>/`, and the intake
record `intake.json` is the second discovery authority beside the bibliography
ledgers — a bibliography has no section for the slides of its own course.

Three findings worth keeping:

- **A deck is not a book, and the book chunker knew nothing about it.** mineru
  returns about one heading per slide, and a slide is 46–144 tokens against a
  `PARENT_TOKENS` of 2000. Every parent would have been a single slide, which
  expands to itself. Slide-shaped sources now chunk by run: 800 tokens, giving
  a median parent of 740 against a median child of 106. See ADR-0008.
- **mineru names its output after the input file, not the slug.** Those agreed
  for forty-three books because a book's slug *is* its filename. They do not
  agree for staged material, and the first eight extractions failed on it.
- **Retrieval is honest about near-duplicates.** Probing every source with its
  own content, 209 of 211 come back. The two that do not are a student summary
  outranked by the deck it summarises, and a draft outranked by its finished
  version. That is the tier ladder working.

## M8: published

`Club-de-la-media-luna/master_kb`, **private**, revision `eb5e2c12`. One rule
decides what goes up: **the repository holds exactly what git cannot**, at the
paths git uses — `courses/<CODE>/raw/literature/*.pdf` and the five declared
artifacts under `derived/`. Everything else in `master_kb` is small text git
already carries, the *guías docentes* included.

5,571 files: 43 acquired books (1.14 GB) and the 5,527 derived artifacts built
from them. Verified by fetching a manifest, a chunk record and a 19 MB PDF back
from that revision and comparing bytes: identical.

The corpus is backed up — the books *and* the index. That took the whole of
M0–M8 to become true.

The first cut published `derived/` alone, under the name `master_kb-derived`,
because that is how M8 was phrased here. It left the books backed up nowhere
and left a revision unable to say which books produced it. Renamed and
re-laid-out before anyone had pulled, which is the only moment that was free.

`corpus.json` in `master_kb` records that revision and is committed, so the
group follows it. The name says what it pins: since the repository carries the
books as well as the artifacts, a revision describes the whole corpus, not just
the derived half.

### What the first push taught us

It was rejected. The Hub reads a file containing a NUL byte as binary and
refuses the commit, and OCR had left 630 NULs in Sutton & Barto — 3,799 control
characters across 13 of the 21 books. They had travelled all the way into the
chunk records and the embedded text, so they were in search results too.

`assemble` now strips them, books converted before the fix were repaired in
place rather than re-extracted, and chunks and the index were rebuilt from the
repaired Markdown. Chunk ids for the affected books changed — they are
content-addressed, and the content changed.

Worth remembering: the corpus had a defect that twelve hours of extraction,
39,036 chunks and a full index build did not surface. Publishing did.

## Intake

Contributors are not organisation members. Each duplicates the public, empty
[template](https://huggingface.co/datasets/Club-de-la-media-luna/master_kb-inbox-template)
into their own account, keeps it private, drops PDFs into `<COURSE>/<kind>/`
and grants a maintainer read access. `rag inbox <repo>` copies what is filed
correctly, writes the bibliography ledger entries, and records the source in
`sources.json`. It refuses public repositories, unknown courses and tiers,
files with no folder, anything under 20 pages, and paths that climb out of the
drop. See [ADR-0007](./adr/0007-contributor-owned-inbox-repositories.md) for
why nobody is invited into the organisation — on the free tier, a shared inbox
would require org-wide `write`, which includes deleting `master_kb-derived`.

## Then

Reranker (only once it can be shown to help), `rag ask` via litellm,
complementary tier, slides and exams tiers, web UI, CI.

## Commands

```sh
uv run rag paths          # resolved locations
uv run rag coverage       # what each course has, and what it does not
uv run rag status         # extracted vs chunked, with per-book warnings
uv run rag books --probe  # the corpus as the ledgers describe it
uv run rag search "..." -k 5 [--course DRL] [--full]
uv run rag serve          # the MCP server, over stdio

uv run rag extract        # resumable; finished books are skipped
uv run rag chunk          # re-chunk everything, refresh the manifest
uv run rag index          # re-embed and rebuild (~25 min on the 3050)
uv run rag push / pull    # the corpus, to and from the Hub (--sources for PDFs)
uv run rag inbox [repo]   # take a contributor's drop into the corpus
```

## Known issues, none blocking

- **Margin biography boxes become headings.** A breadcrumb can read
  `10. Approximate Inference > Leonhard Euler 1707–1783 > 10.1.2 …`. Same class
  as the margin-note problem solved in `assemble.py`; fix belongs there.
- **`EE` has no material at all**, and `IAG` has one book. `rag coverage` says
  so. Lecture slides in September are the real fix.
- **Two ledger entries are wrong**: Whittle (6 pages) and Higham & Kloeden
  (4 pages) are truncated front-matter PDFs marked acquired. Both complementary
  tier, so v1 never touches them, but `fetch_literature.py` validates nothing.
- **`rag pull` records what it asked for, not what it got.** Pulling without a
  pointer records `main`, which is a moving target rather than a pin. Resolving
  the revision to its sha after download would fix it; it only matters once
  more than one person is pushing.
- **No contributor has used the inbox yet.** The path is built and tested —
  template repository, `rag inbox`, `CONTRIBUTING.md` — but it has never run
  against a real contributor's repository, only against fakes. The first real
  drop is the test.
- **No evaluation harness**, by choice. Revisit when the reranker question
  becomes live — that decision is not settleable by spot-checking.
- **No reranker**, by choice. Add only once it can be shown to help.

## Repository state

- All work is on `worktree-design-docs-m0`, pushed, open as
  [iMAT-RAG#1](https://github.com/Club-de-la-media-luna/iMAT-RAG/pull/1).
- [master_kb#5](https://github.com/Club-de-la-media-luna/master_kb/pull/5) adds
  `derived/` to `.gitignore` and is still open. Without it `git status` in
  `master_kb` shows ~700 MB untracked.
