# iMAT-RAG — v1 design

Vocabulary is defined in [CONTEXT.md](../CONTEXT.md). Decisions and their
rejected alternatives are in [docs/adr/](./adr/). This document is the shape of
the thing and the order it gets built in.

## Architecture

```
master_kb/courses/<CODE>/raw/literature/*.pdf   (601 MB, 21 basic books)
                    │
   ┌────────────────▼────────────────┐
   │ EXTRACT   tiered, resumable     │  prose→PyMuPDF · maths+scan→mineru
   │           content-addressed     │  reads content_list.json, not .md
   └────────────────┬────────────────┘
        <slug>.md (LaTeX, page anchors) + <slug>.meta.json + figures/*.png
                    │
   ┌────────────────▼────────────────┐
   │ CHUNK     parent/child          │  split on headings, never mid-equation
   │           breadcrumb-prefixed   │  child ~350 tok → parent ~2000 tok
   └────────────────┬────────────────┘
                    │  ~20k children / ~3k parents
   ┌────────────────▼────────────────┐
   │ EMBED     BGE-M3, local, GPU    │  1024-dim dense + lexical sparse
   └────────────────┬────────────────┘
   ┌────────────────▼────────────────┐
   │ INDEX     LanceDB, one dir      │  vector + BM25 FTS, appendable
   └────────────────┬────────────────┘
          ┌─────────┴─────────┐
     rag search (CLI)     MCP server
     offline, no LLM      search / fetch / coverage
                               └── host agent generates and cites
```

## v1 corpus

21 basic-tier books, 11,990 pages, 601 MB, routed by extraction tier:

| Extraction tier | Pages | Books | Tool |
| --- | ---: | ---: | --- |
| maths (born-digital) | 9,577 | 14 | mineru `-b pipeline` — decided by M2 |
| prose | 1,434 | 5 | PyMuPDF |
| scan (OCR) | 979 | 2 | mineru, same path (`-m auto` selects OCR) |

Coverage per Course, which is uneven by nature and is why `coverage()` exists:

| Course | Basic books |
| --- | --- |
| IAP | 4 — Bishop PRML, Koller & Friedman, Murphy v1, Murphy v2 |
| MD | 4 — Brezis, Evans, Gelfand & Fomin, Lewis & Syrmos |
| IM | 5 — all prose |
| MGP | 3 — Bishop & Bishop, Murphy v1, Murphy v2 |
| DRL | 2 — Sutton & Barto, Lapan |
| GI | 2 — Amari, do Carmo |
| MP | 2 — Goodfellow, Prince |
| IAG | 1 — Bronstein |
| EE | 0 |

Murphy v1 and v2 serve both IAP and MGP. They are stored and embedded once,
tagged `courses: [IAP, MGP]`.

## Stages

**Extract.** Route each Book by extraction tier. mineru emits typed,
page-stamped blocks in `content_list.json`; the Markdown is assembled from those
rather than read from any tool's `.md` output — see
[ADR-0005](./adr/0005-mineru-content-list-as-extraction-source.md). `aside_text`,
`page_number` and `header` blocks are dropped, which removes margin notes,
folios and running heads before they can reach a chunk.

Emit `<slug>.md` — LaTeX for equations, `#`/`##` headings, `<!--page:N-->`
anchors written from `page_idx` — plus `<slug>.meta.json` (title, authors, year,
`courses[]`, both tiers, tool and version, page count, source SHA-256,
warnings). Figures are written to `figures/<slug>/p<N>-fig<M>.png` with their
captions left inline in the Markdown so they stay searchable. Tables become
Markdown tables; algorithm boxes become fenced blocks.

Budget: **≈ 12 hours** for the basic tier on one 4 GB GPU, resumable.

**Chunk.** Walk the heading tree. Never split inside an equation, theorem or
algorithm block. Children (~350 tokens) carry embeddings; each references a
parent (~2000 tokens). Every chunk is prefixed with its breadcrumb. IDs are
`sha256(book_id + page_range + text)[:16]`.

mineru detects headings precisely but flat — `text_level` is always `2`, so `9.1`
and `9.1.1` are indistinguishable and chapter titles are missed. Depth is
reconstructed from the PDF outline where one exists (27 of 41 books) and from the
numbering in the heading text otherwise.

**Embed.** BGE-M3, local, fp16. ~20k children is minutes on a 4 GB GPU.
Cross-lingual by construction — a Spanish query against an English book needs
no translation step.

**Index.** LanceDB, one directory. Chunk metadata: `book_id`, `courses[]`,
`source_tier`, `extraction_tier`, `breadcrumb`, `page_start`, `page_end`,
`language`, `content_type`, `parent_id`. Hybrid retrieval is dense + BM25 fused
with RRF.

**Search.** Hybrid fusion → top ~10 children → expand to parents → return with
citations. No reranker in v1; see *Deferred* below. `--course` filters by
Course.

**MCP server.** `search(query, course?, k?)`, `fetch(chunk_id)` for surrounding
context, `coverage()` so the host agent knows what is not indexed.

## Build order

| | Milestone |
| --- | --- |
| M0 | Rescue the corpus out of the `guide-md-ingest` worktree; commit outstanding ledgers |
| M1 | Repo scaffold — uv, Makefile, `src/imat_rag/`, `tests/` |
| ~~M2~~ | ~~Extraction benchmark~~ — **done**: mineru wins, ≈12 h for the basic tier ([results](./m2-extraction-benchmark.md)) |
| M3 | Extract all 21 basic books |
| M4 | Chunk stage, with determinism tests |
| M5 | Embed and index |
| M6 | `rag search` CLI + coverage report |
| M7 | MCP server |
| M8 | Publish artifacts to HF Hub; group onboarding |

Then, in no fixed order: reranker (only once it can be shown to help),
`rag ask` via litellm, complementary tier, slides and exams tiers, web UI, CI.

## Deferred, deliberately

**No reranker in v1.** A cross-encoder is normally the single largest quality
gain in a RAG system. It is deferred so that it can be added against evidence
rather than assumption. It also has a hardware cost: BGE-M3 and a reranker of
the same class are ~2.2 GB each in fp16 and do not both fit in 4 GB of VRAM
alongside everything else, so adding one means embedding queries on CPU or
quantising.

**No evaluation harness.** Quality is judged by hand. Revisit when the reranker
question becomes live, because that decision is not settleable by spot-checking.

## Known risks

- ~~Marker and MinerU on 4 GB of VRAM is tight.~~ Measured in M2: mineru peaks at
  1.6–1.8 GB, comfortable. marker 1.10.2 peaks at 3951 MB of 4096 and thrashes,
  which is why it was rejected.
- Figure volume is measured, not guessed, and the earlier 100–300 MB estimate was
  about right: **≈ 400 MB** over the basic tier (0.034 MB/page maths, 0.050 scan,
  0.018 prose). The bytes are fine. The **file count** is the awkward part —
  mineru extracts every figure region, 116 from 38 pages of Bishop and 305 from
  50 scanned pages of Evans, so the basic tier lands somewhere near 40,000 small
  files. Worth a minimum-area filter to drop decorative fragments, but it is not
  a blocker.
- Two ledger entries are marked acquired but are truncated front-matter PDFs
  (Whittle, 6 pages; Higham & Kloeden, 4 pages). Both are complementary tier, so
  v1 does not touch them, but the fetch script validates nothing and the ledger
  is wrong.
- `EE` has no material. Nothing in this design fixes that; lecture slides will.
