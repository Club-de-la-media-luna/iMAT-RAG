# Content-addressed, resumable pipeline with hashed chunk identifiers

The four ingest stages — extract, chunk, embed, index — each write artifacts
keyed by `hash(source_sha256 + stage_config)`, and re-running a stage skips
anything already built. Chunk identifiers are `sha256(book_id + page_range +
text)`, not sequence numbers. A committed manifest records which inputs and
configuration produced the current index.

## Considered Options

A Makefile with timestamp-based staleness was rejected because file timestamps
do not notice a *configuration* change: altering the chunk size would silently
reuse chunks built under the old setting. A single rebuild-from-scratch script
was rejected because extraction of ~12,000 pages is an hours-long job that will
be interrupted, and because it makes incremental contribution impossible. DVC
would have covered content-addressing, remote storage and stage dependencies in
one tool, but adds a substantial concept every group member must install and
understand.

## Consequences

Content-addressed chunk IDs are what make multi-contributor merges idempotent:
two people ingesting the same slide deck independently produce byte-identical
IDs, so the union is the correct result with no deduplication pass. This is
load-bearing — the group shares one index and appends to it, so identifiers
must be derivable from content alone and never from insertion order.
