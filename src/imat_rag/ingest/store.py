"""Persist chunks and record what produced them.

Chunks are written as JSON Lines, one file per book: streamable, appendable,
diffable, and readable without loading a whole corpus into memory. The manifest
beside them answers "why did retrieval change?" — it records the configuration
and the source hash behind every book currently in the index.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, Field

from imat_rag.config import Paths
from imat_rag.ingest.chunk import CHILD_TOKENS, PARENT_TOKENS, Chunk, chunk_book
from imat_rag.ingest.extract import BookMeta


class ChunkConfig(BaseModel, frozen=True):
    """Settings that change chunk boundaries, and therefore chunk ids."""

    child_tokens: int = CHILD_TOKENS
    parent_tokens: int = PARENT_TOKENS


class BookChunks(BaseModel):
    """One book's entry in the manifest."""

    slug: str
    source_sha256: str
    stage_key: str
    chunks: int
    parents: int
    children: int
    courses: tuple[str, ...] = ()


class Manifest(BaseModel):
    """What is in the index, and what produced it."""

    chunk_config: ChunkConfig = Field(default_factory=ChunkConfig)
    books: list[BookChunks] = Field(default_factory=list)

    @property
    def total_chunks(self) -> int:
        """Chunks across every book recorded here."""
        return sum(book.chunks for book in self.books)


def chunk_path(paths: Paths, slug: str) -> Path:
    """Where one book's chunks live."""
    return paths.chunks / f"{slug}.jsonl"


def write_chunks(paths: Paths, slug: str, chunks: Iterable[Chunk]) -> int:
    """Write one book's chunks, replacing any previous version."""
    paths.chunks.mkdir(parents=True, exist_ok=True)
    target = chunk_path(paths, slug)
    written = 0
    with target.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(chunk.model_dump_json() + "\n")
            written += 1
    return written


def read_chunks(paths: Paths, slug: str) -> Iterator[Chunk]:
    """Stream one book's chunks back."""
    target = chunk_path(paths, slug)
    if not target.is_file():
        return
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield Chunk.model_validate_json(line)


def read_manifest(paths: Paths) -> Manifest:
    """Load the manifest, or an empty one if this is the first run."""
    if not paths.manifest.is_file():
        return Manifest()
    try:
        return Manifest.model_validate_json(paths.manifest.read_text())
    except (ValueError, OSError):
        return Manifest()


def write_manifest(paths: Paths, manifest: Manifest) -> None:
    """Record what is currently indexed."""
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.books.sort(key=lambda book: book.slug)
    paths.manifest.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def chunk_extracted_book(
    paths: Paths, meta: BookMeta, config: ChunkConfig | None = None
) -> BookChunks:
    """Chunk one extracted book and persist the result."""
    config = config or ChunkConfig()
    markdown = (paths.extracted / f"{meta.slug}.md").read_text(encoding="utf-8")
    chunks = chunk_book(
        markdown,
        meta.slug,
        book_title=meta.titles[0] if meta.titles else meta.slug,
        courses=meta.courses,
        source_tier=meta.tier,
    )
    write_chunks(paths, meta.slug, chunks)

    parents = sum(1 for chunk in chunks if chunk.is_parent)
    return BookChunks(
        slug=meta.slug,
        source_sha256=meta.source_sha256,
        stage_key=meta.stage_key,
        chunks=len(chunks),
        parents=parents,
        children=len(chunks) - parents,
        courses=meta.courses,
    )


def extracted_books(paths: Paths) -> list[BookMeta]:
    """Metadata for every book extracted so far.

    A sidecar that cannot be parsed is skipped rather than fatal: one
    interrupted write must not block chunking everything else.
    """
    found: list[BookMeta] = []
    for sidecar in sorted(paths.extracted.glob("*.meta.json")):
        try:
            found.append(BookMeta.model_validate_json(sidecar.read_text("utf-8")))
        except (ValueError, OSError):
            continue
    return found
