# Getting the corpus running

For everyone in the group. Fifteen minutes, most of it downloading.

You do **not** need to re-extract or re-index anything. Extraction took about
twelve hours on one machine and indexing another twenty-five minutes; the
result is published once and pulled by everyone else.

## What you are getting

21 books from the basic bibliography of nine MIA courses — 11,990 pages —
converted to Markdown, split into 39,036 chunks and embedded into a searchable
index. Ask a question, get back the passages that answer it, each cited to
book, section and page.

It retrieves. It does not generate. Whatever answer you read is written by the
agent you are driving, from passages this returns.

## 1. The two repositories

```sh
git clone git@github.com:Club-de-la-media-luna/iMAT-RAG.git
git clone git@github.com:Club-de-la-media-luna/master_kb.git
```

Code lives in `iMAT-RAG` and is public. Everything else — PDFs, extracted
text, figures, chunks, the index — lives in `master_kb` and is private. Keep
them side by side and nothing needs configuring; otherwise set
`MASTER_KB_PATH` to wherever `master_kb` ended up.

## 2. Install

```sh
cd iMAT-RAG
uv sync --extra index --extra mcp --extra publish
uv run rag paths          # should print paths inside your master_kb
```

The extras are separate on purpose. `index` pulls torch and a 2.2 GB embedding
model; skip it only if you intend to read the Markdown by hand and never
search.

## 3. Pull the artifacts

```sh
uv run rag pull
```

About 414 MB. It reads `derived.json` in `master_kb` — which git tracks — and
downloads exactly the revision recorded there, so everyone in the group is
querying the same index rather than whichever build happens to be newest.

```sh
uv run rag status         # what was extracted and chunked
uv run rag coverage       # what each course has, and what it has not
```

## 4. Ask it something

```sh
uv run rag search "what is a Riemannian metric on a manifold" -k 5
uv run rag search "¿qué es la divergencia de Kullback-Leibler?" --course IAP
```

Queries work in Spanish against English books — the embedding model is
cross-lingual, and there is no translation step to go wrong. The first search
of a session downloads the model and takes ~15 s; later ones are instant.

## 5. Give it to your agent

Register the MCP server with Claude Code, Codex, Gemini CLI, or anything else
that speaks MCP:

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

Three tools: `search`, `fetch` for the sections either side of a passage, and
`coverage`. Ask your agent to check `coverage` before it tells you something is
not in the literature — see below.

## What it will not tell you

**`EE` has no material at all, and `IAG` has one book.** The system reports
this rather than answering from a neighbouring subject. An empty result means
"not in this corpus", which is not the same as "not in the literature", and
`coverage` is how you tell the two apart.

**Only the basic tier is indexed.** Complementary bibliography, lecture slides
and past exams are not in yet.

**Citations are as good as the conversion.** Scanned books went through OCR;
`do Carmo` and the differential-models scans are retrievable but their
breadcrumbs occasionally pick up a margin note as a heading. If a citation
looks odd, `fetch` the chunk and read around it.

## Two rules

**Never commit anything under `derived/` to git.** It is gitignored for a
reason: one book alone is 144 MB, above GitHub's hard limit, and the whole
payload would exhaust the free LFS tier in a handful of clones.

**Never make the dataset repository public.** Embeddings can be inverted back
towards approximations of the text they were built from, so a public index of
copyrighted textbooks is a weaker form of publishing the textbooks. This is
why the Hub repo is private rather than merely unlisted — see
[ADR-0001](./adr/0001-public-code-private-data.md).

## If you add material

```sh
uv run rag extract        # resumable; finished books are skipped
uv run rag chunk
uv run rag index
uv run rag push -m "add the IM slides"
```

Then commit the updated `derived.json` in `master_kb`. That pointer is what
tells everyone else which revision to pull; without it your upload exists but
nobody follows it.

Chunk ids are content-addressed, so two people ingesting the same book
independently produce identical ids and the union of their work is the correct
result — there is no deduplication pass to run.
