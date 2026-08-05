from __future__ import annotations

from pathlib import Path
from typing import Any

from imat_rag.config import Paths
from imat_rag.index.search import fetch
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.store import BookChunks, Manifest, write_chunks, write_manifest


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_chunk(
    chunk_id: str,
    text: str,
    *,
    book_slug: str = "bishop",
    parent_id: str = "",
    is_parent: bool = False,
    **extra: Any,
) -> Chunk:
    fields: dict[str, Any] = {
        "chunk_id": chunk_id,
        "book_slug": book_slug,
        "breadcrumb": f"{book_slug} > {text}",
        "text": text,
        "page_start": 1,
        "page_end": 2,
        "parent_id": parent_id,
        "is_parent": is_parent,
        "courses": ("IAP",),
        "tokens": len(text) // 4,
    }
    fields.update(extra)
    return Chunk(**fields)


def seed(paths: Paths) -> None:
    """Two books, each a run of parent sections in document order."""
    bishop = [
        a_chunk("p1", "9.1 K-means", is_parent=True, page_start=10, page_end=14),
        a_chunk("c1", "means clustering", parent_id="p1", page_start=10, page_end=11),
        a_chunk("p2", "9.2 Mixtures", is_parent=True, page_start=15, page_end=20),
        a_chunk("c2", "gaussian mixtures", parent_id="p2", page_start=15, page_end=16),
        a_chunk("p3", "9.3 EM", is_parent=True, page_start=21, page_end=30),
    ]
    carmo = [
        a_chunk("q1", "2.1 Metrics", book_slug="do-carmo", is_parent=True),
        a_chunk("q2", "2.2 Curvature", book_slug="do-carmo", is_parent=True),
    ]
    write_chunks(paths, "bishop", bishop)
    write_chunks(paths, "do-carmo", carmo)
    write_manifest(
        paths,
        Manifest(
            books=[
                BookChunks(
                    slug="bishop",
                    source_sha256="0" * 64,
                    stage_key="k",
                    chunks=len(bishop),
                    parents=3,
                    children=2,
                    courses=("IAP",),
                ),
                BookChunks(
                    slug="do-carmo",
                    source_sha256="1" * 64,
                    stage_key="k",
                    chunks=len(carmo),
                    parents=2,
                    children=0,
                    courses=("GI",),
                ),
            ]
        ),
    )


def test_fetching_a_section_returns_it_with_its_citation(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = fetch(paths, "p2")

    assert found is not None
    assert found.chunk.chunk_id == "p2"
    assert found.chunk.text == "9.2 Mixtures"
    assert found.chunk.citation == "bishop > 9.2 Mixtures, pp. 15-20"


def test_neighbours_are_the_adjacent_sections_in_document_order(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = fetch(paths, "p2")

    assert found is not None
    assert found.previous is not None and found.previous.chunk_id == "p1"
    assert found.following is not None and found.following.chunk_id == "p3"


def test_the_first_section_of_a_book_has_no_previous(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = fetch(paths, "p1")

    assert found is not None
    assert found.previous is None
    assert found.following is not None and found.following.chunk_id == "p2"


def test_the_last_section_of_a_book_has_no_following(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = fetch(paths, "p3")

    assert found is not None
    assert found.following is None


def test_neighbours_never_cross_into_another_book(tmp_path: Path) -> None:
    """`do-carmo` continues after `bishop` on disk, but not in any argument."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = fetch(paths, "q1")

    assert found is not None
    assert found.previous is None
    assert found.following is not None and found.following.chunk_id == "q2"


def test_fetching_a_child_returns_the_section_it_belongs_to(tmp_path: Path) -> None:
    """A child is what matched; the parent is what is worth reading."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = fetch(paths, "c2")

    assert found is not None
    assert found.chunk.chunk_id == "p2"
    assert found.chunk.matched_text == "gaussian mixtures"


def test_fetching_an_unknown_id_returns_nothing(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    assert fetch(paths, "does-not-exist") is None


def test_fetching_from_an_empty_knowledge_base_returns_nothing(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")

    assert fetch(paths, "p1") is None
