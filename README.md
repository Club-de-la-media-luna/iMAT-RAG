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

## Status

Pre-implementation. Design settled; see the build order in `docs/design.md`.
