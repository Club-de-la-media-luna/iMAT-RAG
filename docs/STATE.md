# Where things stand

Resume point for the next session. Read [CONTEXT.md](../CONTEXT.md) for
vocabulary, [design.md](./design.md) for the shape, [adr/](./adr/) for why.

Last updated after M6.

## Done: M0 – M6

The system works end to end. `rag search` returns correctly cited passages from
21 books.

| | |
| --- | --- |
| Corpus | 21 basic-tier books, 11,990 pages, 601 MB of PDFs |
| Extracted | ~29.9M characters, complete page coverage on every book, 0 failures |
| Chunked | 39,036 chunks — 10,890 parents, 28,146 children, 7.2M tokens |
| Indexed | 28,146 children embedded with BGE-M3, 173 MB LanceDB, 2 tables |
| Tests | 129 passing, lint 10.00/10 |

Two results that closed open risks:

- **Cross-lingual retrieval works.** `¿qué es la divergencia de
  Kullback-Leibler?` returns Bishop PRML §10.1.2 — Spanish query, English book,
  no translation step.
- **OCR'd mathematics is retrievable.** `what is a Riemannian metric on a
  manifold` returns do Carmo ch. 2, pp. 52–54, from a scanned PDF with no text
  layer. GI and MD are not write-offs.

## Next: M7 and M8

**M7 — MCP server.** Expose three tools over the existing
`imat_rag.index.search`:

- `search(query, course?, k?)` → the `Hit` list, already carrying `.citation`
- `fetch(chunk_id)` → one chunk plus its neighbours, for following context
- `coverage()` → per-course book/page/chunk counts, so the host agent knows what
  is missing rather than guessing

The retrieval half is done and tested; M7 is a protocol wrapper over
`search()` in `src/imat_rag/index/search.py`. No new retrieval logic.

**M8 — publish.** Push `derived/` to a **private** Hugging Face dataset repo
under `Club-de-la-media-luna` (see [ADR-0001](./adr/0001-public-code-private-data.md)),
add `rag pull`, and write the group onboarding note. Nothing in `derived/` is
backed up anywhere today — this is the only step that changes that.

## Commands

```sh
uv run rag paths          # resolved locations
uv run rag coverage       # what each course has, and what it does not
uv run rag status         # extracted vs chunked, with per-book warnings
uv run rag books --probe  # the corpus as the ledgers describe it
uv run rag search "..." -k 5 [--course DRL] [--full]

uv run rag extract        # resumable; finished books are skipped
uv run rag chunk          # re-chunk everything, refresh the manifest
uv run rag index          # re-embed and rebuild (~25 min on the 3050)
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
- **No evaluation harness**, by choice. Revisit when the reranker question
  becomes live — that decision is not settleable by spot-checking.
- **No reranker**, by choice. Add only once it can be shown to help.

## Repository state

- All work is on `worktree-design-docs-m0`, pushed, open as
  [iMAT-RAG#1](https://github.com/Club-de-la-media-luna/iMAT-RAG/pull/1).
- [master_kb#5](https://github.com/Club-de-la-media-luna/master_kb/pull/5) adds
  `derived/` to `.gitignore` and is still open. Without it `git status` in
  `master_kb` shows ~700 MB untracked.
