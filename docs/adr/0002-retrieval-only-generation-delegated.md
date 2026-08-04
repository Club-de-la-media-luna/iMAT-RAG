# v1 retrieves; the MCP host generates

The system exposes search over the corpus and returns cited passages. It does
not call a language model, hold an API key, or produce prose answers. Answer
generation is delegated to whatever agent is already driving it — Claude Code,
Codex, or Gemini CLI — via an MCP server exposing `search`, `fetch` and
`coverage` tools.

## Considered Options

Building `rag ask` with a provider abstraction (litellm) was the obvious
alternative and remains the planned follow-up. It was rejected for v1 because
the group uses three different model providers, so any built-in generator is
wrong for two thirds of them; because no member currently has API keys
configured; and because retrieval quality, not prompting, is what determines
whether this is useful. Bundling a small local model for offline generation was
rejected separately: a 4B-class model is the largest that fits the available
4 GB of VRAM, and confidently wrong graduate-level derivations are worse than
no answer.

## Consequences

Provider-agnosticism is achieved by having no provider. Query rewriting,
multi-hop search and citation formatting come free, because the host agent
already does them. The CLI's `search` command is fully offline, which requires
that embeddings stay local (see ADR-0003's sibling constraint) — an embedding
API in the query path would silently reintroduce the network dependency this
decision exists to avoid.
