from __future__ import annotations

from pathlib import Path
from typing import Any

from imat_rag.config import Paths
from imat_rag.index import lance
from imat_rag.index.embed import EmbedConfig, batched, encode_texts, resolve_device
from imat_rag.index.search import Hit, build, search
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.store import BookChunks, Manifest, write_chunks, write_manifest


class FakeEncoder:
    """Deterministic stand-in for BGE-M3.

    The index layer must be testable without a 2.2 GB model download, so the
    encoder is injected. Vectors are keyed off word overlap so that relevance
    ordering is still meaningful.
    """

    dimensions = 8
    vocabulary = (
        "mixture models expectation maximisation gaussian riemannian manifold curvature"
    ).split()

    def encode(self, sentences: Any, **_: Any) -> Any:
        rows = []
        for sentence in sentences:
            words = set(str(sentence).lower().split())
            rows.append([1.0 if term in words else 0.0 for term in self.vocabulary])
        return rows


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_chunk(
    chunk_id: str, text: str, parent_id: str = "", is_parent: bool = False, **extra: Any
) -> Chunk:
    fields: dict[str, Any] = {
        "chunk_id": chunk_id,
        "book_slug": "bishop",
        "breadcrumb": "Bishop PRML > 9. Mixture Models",
        "text": text,
        "page_start": 1,
        "page_end": 2,
        "parent_id": parent_id,
        "is_parent": is_parent,
        "courses": ("IAP", "MGP"),
        "tokens": len(text) // 4,
    }
    fields.update(extra)
    return Chunk(**fields)


def seed(paths: Paths) -> None:
    chunks = [
        a_chunk("p1", "mixture models and expectation maximisation", is_parent=True),
        a_chunk("c1", "mixture models", parent_id="p1"),
        a_chunk("c2", "expectation maximisation gaussian", parent_id="p1"),
        a_chunk(
            "p2",
            "riemannian manifold curvature",
            is_parent=True,
            book_slug="do-carmo",
            courses=("GI",),
        ),
        a_chunk(
            "c3",
            "riemannian manifold",
            parent_id="p2",
            book_slug="do-carmo",
            courses=("GI",),
        ),
    ]
    write_chunks(paths, "bishop", chunks)
    write_manifest(
        paths,
        Manifest(
            books=[
                BookChunks(
                    slug="bishop",
                    source_sha256="a",
                    stage_key="k",
                    chunks=len(chunks),
                    parents=2,
                    children=3,
                )
            ]
        ),
    )


# --- embedding helpers ------------------------------------------------------


def test_batching_covers_every_item() -> None:
    items = list(range(10))

    assert [list(b) for b in batched(items, 4)] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]


def test_batching_an_empty_sequence_yields_nothing() -> None:
    assert list(batched([], 4)) == []


def test_encoding_no_texts_returns_no_vectors() -> None:
    assert encode_texts(FakeEncoder(), []) == []


def test_an_explicit_device_is_respected() -> None:
    assert resolve_device("cpu") == "cpu"


def test_vectors_are_plain_floats(tmp_path: Path) -> None:
    """LanceDB stores lists, not tensors."""
    vectors = encode_texts(FakeEncoder(), ["mixture models"])

    assert all(isinstance(value, float) for value in vectors[0])


# --- building ---------------------------------------------------------------


def test_building_writes_children_and_parents(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)

    children, parents = build(paths, EmbedConfig(), FakeEncoder())

    assert (children, parents) == (3, 2)
    db = lance.connect(paths.index)
    assert set(db.table_names()) == {lance.CHILDREN, lance.PARENTS}
    assert db.open_table(lance.CHILDREN).count_rows() == 3


def test_parents_are_stored_without_vectors(tmp_path: Path) -> None:
    """Parents are fetched, never matched; embedding them would be waste."""
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    table = lance.connect(paths.index).open_table(lance.PARENTS)
    row = table.to_arrow().to_pylist()[0]

    assert lance.VECTOR_FIELD not in row


def test_rebuilding_replaces_rather_than_duplicating(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)

    build(paths, EmbedConfig(), FakeEncoder())
    build(paths, EmbedConfig(), FakeEncoder())

    assert lance.connect(paths.index).open_table(lance.CHILDREN).count_rows() == 3


def test_the_embedded_text_carries_the_breadcrumb(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    rows = lance.connect(paths.index).open_table(lance.CHILDREN).to_arrow().to_pylist()

    assert all(row["text"].startswith("Bishop PRML") for row in rows)


# --- searching --------------------------------------------------------------


def test_searching_an_empty_index_returns_nothing(tmp_path: Path) -> None:
    assert search(make_kb(tmp_path), "anything", encoder=FakeEncoder()) == []


def test_a_query_finds_the_relevant_passage(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    hits = search(paths, "mixture models", limit=3, encoder=FakeEncoder())

    assert hits
    assert "mixture" in hits[0].text.lower()


def test_matches_are_expanded_to_their_parent(tmp_path: Path) -> None:
    """The child matched; the parent is what is worth reading."""
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    hits = search(paths, "expectation maximisation", limit=3, encoder=FakeEncoder())

    assert hits[0].chunk_id in {"p1", "p2"}
    assert hits[0].matched_text


def test_expansion_can_be_turned_off(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    hits = search(paths, "mixture models", expand=False, encoder=FakeEncoder())

    assert hits[0].chunk_id.startswith("c")


def test_two_children_of_one_parent_yield_one_hit(tmp_path: Path) -> None:
    """Otherwise the same section is returned twice."""
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    hits = search(
        paths, "mixture models expectation maximisation", limit=5, encoder=FakeEncoder()
    )

    assert len({h.chunk_id for h in hits}) == len(hits)


def test_a_course_filter_scopes_the_search(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    gi = search(paths, "manifold", course="GI", limit=5, encoder=FakeEncoder())

    assert gi
    assert all("GI" in h.courses for h in gi)


def test_a_course_with_no_material_returns_nothing(tmp_path: Path) -> None:
    """EE has no books; the system must say so rather than answer from GI."""
    paths = make_kb(tmp_path)
    seed(paths)
    build(paths, EmbedConfig(), FakeEncoder())

    assert search(paths, "ethics", course="EE", limit=5, encoder=FakeEncoder()) == []


# --- citations --------------------------------------------------------------


def test_a_citation_names_the_section_and_pages() -> None:
    hit = Hit(
        chunk_id="x",
        book_slug="bishop",
        breadcrumb="Bishop PRML > 9.4 The EM Algorithm",
        text="...",
        page_start=439,
        page_end=441,
        courses=("IAP",),
        score=1.0,
    )

    assert hit.citation == "Bishop PRML > 9.4 The EM Algorithm, pp. 439-441"


def test_a_single_page_citation_is_singular() -> None:
    hit = Hit(
        chunk_id="x",
        book_slug="b",
        breadcrumb="B > 1",
        text="...",
        page_start=7,
        page_end=7,
        courses=(),
        score=0.0,
    )

    assert hit.citation.endswith("p. 7")
