# Where things stand

Resume point for the next session. Read [CONTEXT.md](../CONTEXT.md) for
vocabulary, [design.md](./design.md) for the shape, [adr/](./adr/) for why.

Last updated after M7, and after M8's code but not its upload.

## Done: M0 – M7

The system works end to end, from the CLI and over MCP. `rag search` and the
`search` tool return the same correctly cited passages from 21 books.

| | |
| --- | --- |
| Corpus | 21 basic-tier books, 11,990 pages, 601 MB of PDFs |
| Extracted | ~29.9M characters, complete page coverage on every book, 0 failures |
| Chunked | 39,036 chunks — 10,890 parents, 28,146 children, 7.2M tokens |
| Indexed | 28,146 children embedded with BGE-M3, 173 MB LanceDB, 2 tables |
| Artifacts | ~414 MB publishable (`extracted`, `figures`, `chunks`, `index`, manifest) |
| Tests | 178 passing, lint 10.00/10 |

Three results that closed open risks:

- **Cross-lingual retrieval works.** `¿qué es la divergencia de
  Kullback-Leibler?` returns Bishop PRML §10.1.2 — Spanish query, English book,
  no translation step.
- **OCR'd mathematics is retrievable.** `what is a Riemannian metric on a
  manifold` returns do Carmo ch. 2, pp. 52–54, from a scanned PDF with no text
  layer. GI and MD are not write-offs.
- **The MCP server answers over real stdio.** Verified with an actual client:
  handshake, three tools listed, `coverage` reporting `EE` as the one course
  with no material. `fetch` costs 0.05 s on the real 39k-chunk corpus.

## M8: written, not executed

`rag push` and `rag pull` exist and are tested; the onboarding note is
[written](./onboarding.md). **Nothing has been uploaded.** Two things are
missing, and neither is a code problem:

1. **The Hugging Face organisation does not exist.** `Club-de-la-media-luna` is
   a GitHub organisation; there is no account of that name on the Hub —
   `/api/organizations/Club-de-la-media-luna/overview` is a 404. Someone has to
   create it (or the group has to pick another namespace, in which case change
   `DEFAULT_REPO` in `src/imat_rag/publish.py`).
2. **The local token is read-only.** `huggingface_hub.HfApi().whoami()` reports
   `JES0406`, role `read`, no organisations. Publishing needs a write token:
   `huggingface-cli login` with one created at
   <https://huggingface.co/settings/tokens>.

`rag push` was run against the real Hub and refused as expected, with the
guidance above rather than a traceback:

```
403 Forbidden: You don't have the rights to create a dataset under the
namespace "Club-de-la-media-luna".
```

No pointer was written, so nothing claims to have been published.

With both in place the whole of M8 is:

```sh
uv run rag push -m "first publish of the basic tier"
# then, in master_kb, commit the derived.json it wrote
```

`push` creates the repository private, refuses to upload into a public one,
and uploads only the five declared artifacts — `bench`, `blocks` and `work`
are scratch and would nearly double the payload. It writes `derived.json`
beside `derived/`, and that pointer is what makes `rag pull` reproducible:
everyone gets the recorded revision rather than whatever the tip happens to
be.

**`derived/` is still backed up nowhere.** That is what this step is for.

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
uv run rag push / pull    # the artifacts, to and from the Hub
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
- **No evaluation harness**, by choice. Revisit when the reranker question
  becomes live — that decision is not settleable by spot-checking.
- **No reranker**, by choice. Add only once it can be shown to help.

## Repository state

- All work is on `worktree-design-docs-m0`, pushed, open as
  [iMAT-RAG#1](https://github.com/Club-de-la-media-luna/iMAT-RAG/pull/1).
- [master_kb#5](https://github.com/Club-de-la-media-luna/master_kb/pull/5) adds
  `derived/` to `.gitignore` and is still open. Without it `git status` in
  `master_kb` shows ~700 MB untracked.
