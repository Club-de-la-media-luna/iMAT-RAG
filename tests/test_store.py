from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.extract import BookMeta
from imat_rag.ingest.store import (
    BookChunks,
    ChunkConfig,
    Manifest,
    chunk_extracted_book,
    extracted_books,
    read_chunks,
    read_manifest,
    write_chunks,
    write_manifest,
)

MARKDOWN = """\
<!--page:0-->

# 1. Introduction

Some prose about the subject.

<!--page:1-->

## 1.1 Details

More prose here.
"""

META = BookMeta(
    slug="a-book",
    courses=("IAP", "MGP"),
    titles=("Author, A. — A Book",),
    tier=2,
    extraction_tier="born_digital",
    pages=2,
    page_span=(0, 1),
    source_sha256="f" * 64,
    source_path="/kb/a-book.pdf",
    stage_key="0123456789abcdef",
    tool="mineru pipeline",
    figures=0,
    chars=len(MARKDOWN),
)


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_chunk(chunk_id: str = "abc", **overrides: object) -> Chunk:
    fields: dict[str, object] = {
        "chunk_id": chunk_id,
        "book_slug": "a-book",
        "breadcrumb": "A Book > 1. Introduction",
        "text": "Some prose.",
        "page_start": 0,
        "page_end": 1,
    }
    fields.update(overrides)
    return Chunk(**fields)  # type: ignore[arg-type]


# --- round trip -------------------------------------------------------------


def test_chunks_survive_a_write_and_read(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    written = [a_chunk("one"), a_chunk("two", is_parent=True)]

    assert write_chunks(paths, "a-book", written) == 2
    assert [c.chunk_id for c in read_chunks(paths, "a-book")] == ["one", "two"]


def test_reading_a_book_that_was_never_chunked_yields_nothing(tmp_path: Path) -> None:
    assert list(read_chunks(make_kb(tmp_path), "missing")) == []


def test_rewriting_replaces_rather_than_appends(tmp_path: Path) -> None:
    """Re-chunking a book must not leave its previous chunks behind."""
    paths = make_kb(tmp_path)
    write_chunks(paths, "a-book", [a_chunk("one"), a_chunk("two")])

    write_chunks(paths, "a-book", [a_chunk("three")])

    assert [c.chunk_id for c in read_chunks(paths, "a-book")] == ["three"]


def test_every_field_survives_the_round_trip(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    original = a_chunk(
        "x", courses=("IAP", "MGP"), source_tier=2, parent_id="p", tokens=42
    )

    write_chunks(paths, "a-book", [original])

    assert next(iter(read_chunks(paths, "a-book"))) == original


# --- manifest ---------------------------------------------------------------


def test_a_missing_manifest_reads_as_empty(tmp_path: Path) -> None:
    manifest = read_manifest(make_kb(tmp_path))

    assert manifest.books == []
    assert manifest.total_chunks == 0


def test_a_corrupt_manifest_reads_as_empty(tmp_path: Path) -> None:
    """An interrupted write must not crash the next run."""
    paths = make_kb(tmp_path)
    paths.manifest.parent.mkdir(parents=True)
    paths.manifest.write_text("{ truncated")

    assert read_manifest(paths).books == []


def test_the_manifest_round_trips_and_sorts(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    manifest = Manifest(
        books=[
            BookChunks(
                slug="zeta",
                source_sha256="a",
                stage_key="k",
                chunks=3,
                parents=1,
                children=2,
            ),
            BookChunks(
                slug="alpha",
                source_sha256="b",
                stage_key="k",
                chunks=5,
                parents=2,
                children=3,
            ),
        ]
    )

    write_manifest(paths, manifest)
    loaded = read_manifest(paths)

    assert [b.slug for b in loaded.books] == ["alpha", "zeta"]
    assert loaded.total_chunks == 8


def test_the_manifest_records_the_chunk_config(tmp_path: Path) -> None:
    """The answer to 'why did retrieval change?'."""
    paths = make_kb(tmp_path)
    write_manifest(paths, Manifest(chunk_config=ChunkConfig(child_tokens=500)))

    assert read_manifest(paths).chunk_config.child_tokens == 500


# --- chunking an extracted book ---------------------------------------------


def test_an_extracted_book_is_chunked_and_persisted(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "a-book.md").write_text(MARKDOWN)

    entry = chunk_extracted_book(paths, META)

    assert entry.chunks == entry.parents + entry.children
    assert entry.parents > 0 and entry.children > 0
    assert entry.courses == ("IAP", "MGP")
    assert len(list(read_chunks(paths, "a-book"))) == entry.chunks


def test_chunks_carry_the_books_courses_and_tier(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "a-book.md").write_text(MARKDOWN)

    chunk_extracted_book(paths, META)
    chunks = list(read_chunks(paths, "a-book"))

    assert all(c.courses == ("IAP", "MGP") for c in chunks)
    assert all(c.source_tier == 2 for c in chunks)


def test_the_breadcrumb_starts_with_the_book_title(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "a-book.md").write_text(MARKDOWN)

    chunk_extracted_book(paths, META)

    assert all(
        c.breadcrumb.startswith("Author, A. — A Book")
        for c in read_chunks(paths, "a-book")
    )


def test_the_manifest_entry_carries_the_source_hash(tmp_path: Path) -> None:
    """A chunk set must be traceable to the bytes it came from."""
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "a-book.md").write_text(MARKDOWN)

    entry = chunk_extracted_book(paths, META)

    assert entry.source_sha256 == "f" * 64
    assert entry.stage_key == "0123456789abcdef"


# --- discovering what has been extracted ------------------------------------


def test_extracted_books_are_listed_in_order(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    for slug in ("zeta", "alpha"):
        (paths.extracted / f"{slug}.meta.json").write_text(
            META.model_copy(update={"slug": slug}).model_dump_json()
        )

    assert [b.slug for b in extracted_books(paths)] == ["alpha", "zeta"]


def test_a_corrupt_sidecar_is_skipped_not_fatal(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "good.meta.json").write_text(
        META.model_copy(update={"slug": "good"}).model_dump_json()
    )
    (paths.extracted / "bad.meta.json").write_text("{ truncated")

    assert [b.slug for b in extracted_books(paths)] == ["good"]
