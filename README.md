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

## Status

**Working end to end.** 21 books indexed; `rag search` returns cited passages,
including Spanish queries against English books and passages recovered by OCR
from scanned PDFs. `rag serve` answers the same questions over MCP.

M0–M7 done. M8 (publish to Hugging Face) remains — see
**[docs/STATE.md](./docs/STATE.md)**, which is the resume point.
