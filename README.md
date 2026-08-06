# iMAT-RAG

Retrieval over the reading list of the Máster Universitario en Inteligencia
Artificial. Ask a question about course material, get the passages that answer
it, cited to book, section and page.

It retrieves; it does not generate. Answers are produced by whatever agent is
driving it — Claude Code, Codex, Gemini CLI — through an MCP server.

This repository holds **code only**. All corpus data (PDFs, extracted Markdown,
figures, chunks, index) lives in the private `master_kb` repository and its
Hugging Face Hub dataset repository.

## Docs

- [CONTRIBUTING.md](./CONTRIBUTING.md) — adding material (no tooling needed), and code conventions.
- [docs/onboarding.md](./docs/onboarding.md) — for the group: how to get it running.
- [CONTEXT.md](./CONTEXT.md) — the vocabulary. Read this first.
- [docs/design.md](./docs/design.md) — architecture, corpus, stages, build order.
- [docs/adr/](./docs/adr/) — decisions and the alternatives that were rejected.
- [docs/STATE.md](./docs/STATE.md) — what is done, what is next, known issues.
- [docs/m2-extraction-benchmark.md](./docs/m2-extraction-benchmark.md) — why mineru.

## Getting started

```sh
make install          # uv sync
make test             # pytest
make lint             # isort, black, mypy, flake8, ruff, complexipy, pylint
uv run rag paths      # show the resolved knowledge base and artifact locations
```

The knowledge base is found at runtime: `MASTER_KB_PATH` if set (authoritative
— a wrong value is an error, not a reason to look elsewhere), otherwise the
nearest `master_kb` directory at or above the working directory.

## The MCP server

`rag serve` exposes the corpus to an agent over MCP. Three tools:

| | |
| --- | --- |
| `search(query, course?, k?)` | Passages answering a question, each with its citation |
| `fetch(chunk_id)` | One passage again, with the sections either side of it |
| `coverage()` | What each course has indexed, and what it does not |

`coverage` exists so that silence is legible. Several courses have no material
at all; without it, an empty `search` result reads as "not in the literature"
rather than "not in this corpus".

Register it with a host agent — Claude Code, Codex, Gemini CLI — as a stdio
server:

```json
{
  "mcpServers": {
    "imat-rag": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/iMAT-RAG", "rag", "serve"],
      "env": { "MASTER_KB_PATH": "/path/to/master_kb" }
    }
  }
}
```

Install the extras it needs with `uv sync --extra index --extra mcp`. The first
`search` of a session loads BGE-M3 and takes ~15 s; every one after is instant,
and `coverage` never loads it at all.

## Taking in new material

Contributors keep their own repository rather than joining the organisation:
they duplicate the public
[inbox template](https://huggingface.co/datasets/Club-de-la-media-luna/master_kb-inbox-template),
make it private, drop PDFs into `<COURSE>/<kind>/`, and share the name.

```sh
uv run rag inbox someone/master_kb-inbox   # take it, and register the source
uv run rag inbox                           # re-take every registered source
```

It copies rather than references, writes the bibliography ledger entries, and
refuses what it cannot place — public repositories, unknown course codes,
files with no folder, front matter under 20 pages. See
[CONTRIBUTING.md](./CONTRIBUTING.md) and
[ADR-0007](./docs/adr/0007-contributor-owned-inbox-repositories.md).

## The corpus on the Hub

One rule decides what is published: **the dataset repository holds exactly what
git cannot**, at the paths git uses.

```
Club-de-la-media-luna/master_kb   (private)
  courses/<CODE>/raw/literature/*.pdf    the 43 acquired books, 1.14 GB
  derived/extracted|chunks|figures|index, manifest.json   ~414 MB
```

`master_kb` gitignores exactly those two things — one book alone exceeds
GitHub's file limit — so everything else there is small text git already
carries, the *guías docentes* included. Mirroring the knowledge base rather than shipping `derived/` alone is
what lets one revision be a complete statement: *these* sources, and the index
built from them.

```sh
uv run rag pull                 # the revision recorded in master_kb/derived.json
uv run rag pull --sources       # and the source PDFs, for re-extracting
uv run rag pull --revision abc  # or an exact revision
uv run rag push -m "..."        # publish, and record the revision it created
```

`pull` leaves the PDFs behind by default: searching needs the index, not 1.1 GB
of books nobody will open.

`push` refuses to upload into a public repository. The index is as private as
the PDFs it was built from — embeddings can be inverted back towards their
source text — so this is not merely a size decision; see
[ADR-0001](./docs/adr/0001-public-code-private-data.md).

## Status

**Working end to end.** 21 books indexed; `rag search` returns cited passages,
including Spanish queries against English books and passages recovered by OCR
from scanned PDFs. `rag serve` answers the same questions over MCP.

M0–M8 done. The artifacts are published to a private Hugging Face dataset
repository — 5,528 files, revision `02b759af` — so `rag pull` gives a new
group member a working index without re-extracting anything. See
**[docs/STATE.md](./docs/STATE.md)**, which is the resume point.
