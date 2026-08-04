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

## Status

M1 done — scaffold, config resolution, CLI skeleton. Next is M2, the extraction
benchmark. See the build order in [docs/design.md](./docs/design.md).
