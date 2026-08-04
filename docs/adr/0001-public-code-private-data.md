# Public code repository, private data repository, artifacts on Hugging Face Hub

`iMAT-RAG` is public and holds only code, config and tests. All corpus data —
source PDFs, extracted Markdown, figures, chunks and the built index — lives in
the private `master_kb` repository and its associated private Hugging Face Hub
dataset repository under the `Club-de-la-media-luna` organisation. The code
repository never contains data, and the data repository never contains
retrieval code.

## Considered Options

Committing the corpus to `master_kb` via Git LFS was rejected on hard limits:
one basic-tier book (Murphy, *Probabilistic Machine Learning: Advanced Topics*)
is 144 MB, above GitHub's 100 MB per-file hard limit, and the v1 payload is
roughly 900 MB against a free LFS tier of 1 GB storage and 1 GB/month
bandwidth — a handful of clones exhausts it. Google Drive and Cloudflare R2
were both viable; HF Hub won because it versions revisions natively, so
`--revision` pins an exact index build and a contributor adding material
creates a new revision rather than overwriting a shared folder.

## Consequences

`master_kb` git keeps only small text — guides, ledgers, manifests — which
*point at* HF revisions. Reproducing an index therefore requires two fetches
(git for the manifest, HF for the artifacts), and the manifest is what binds
them.
