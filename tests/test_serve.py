from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imat_rag.config import Paths
from imat_rag.index.embed import EmbedConfig
from imat_rag.index.search import build
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.extract import BookMeta
from imat_rag.ingest.store import BookChunks, Manifest, write_chunks, write_manifest
from imat_rag.serve import build_server


class FakeEncoder:
    """Deterministic stand-in for BGE-M3, keyed off word overlap."""

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
    chunk_id: str,
    text: str,
    *,
    book_slug: str = "bishop",
    parent_id: str = "",
    is_parent: bool = False,
    courses: tuple[str, ...] = ("IAP", "MGP"),
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        book_slug=book_slug,
        breadcrumb=f"{book_slug} > 9. Mixture Models",
        text=text,
        page_start=10,
        page_end=14,
        parent_id=parent_id,
        is_parent=is_parent,
        courses=courses,
        tokens=len(text) // 4,
    )


def a_sidecar(paths: Paths, slug: str, courses: tuple[str, ...]) -> None:
    meta = BookMeta(
        slug=slug,
        courses=courses,
        titles=(slug,),
        tier=2,
        extraction_tier="prose",
        pages=750,
        page_span=(1, 750),
        source_sha256="0" * 64,
        source_path=f"/books/{slug}.pdf",
        stage_key="k",
        tool="mineru",
        figures=0,
        chars=10,
    )
    paths.extracted.mkdir(parents=True, exist_ok=True)
    (paths.extracted / f"{slug}.meta.json").write_text(
        meta.model_dump_json(), encoding="utf-8"
    )


def seed(paths: Paths) -> None:
    bishop = [
        a_chunk("p1", "mixture models and expectation maximisation", is_parent=True),
        a_chunk("c1", "mixture models", parent_id="p1"),
        a_chunk("p2", "gaussian maximisation", is_parent=True),
    ]
    carmo = [
        a_chunk(
            "q1",
            "riemannian manifold curvature",
            book_slug="do-carmo",
            is_parent=True,
            courses=("GI",),
        ),
        a_chunk(
            "d1",
            "riemannian manifold",
            book_slug="do-carmo",
            parent_id="q1",
            courses=("GI",),
        ),
    ]
    write_chunks(paths, "bishop", bishop)
    write_chunks(paths, "do-carmo", carmo)
    a_sidecar(paths, "bishop", ("IAP", "MGP"))
    a_sidecar(paths, "do-carmo", ("GI",))
    write_manifest(
        paths,
        Manifest(
            books=[
                BookChunks(
                    slug="bishop",
                    source_sha256="a",
                    stage_key="k",
                    chunks=3,
                    parents=2,
                    children=1,
                    courses=("IAP", "MGP"),
                ),
                BookChunks(
                    slug="do-carmo",
                    source_sha256="b",
                    stage_key="k",
                    chunks=2,
                    parents=1,
                    children=1,
                    courses=("GI",),
                ),
            ]
        ),
    )
    build(paths, EmbedConfig(), FakeEncoder())


def call(server: Any, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    """Invoke a tool the way a host agent would, without a transport."""
    return asyncio.run(server.call_tool(tool, arguments or {}))


def tools_of(server: Any) -> Any:
    return asyncio.run(server.list_tools())


def result_of(server: Any, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    outcome = call(server, tool, arguments)
    assert not outcome.is_error, outcome.content
    content = outcome.structured_content
    # A list return is wrapped under `result`; a single model is not.
    return content["result"] if set(content) == {"result"} else content


def a_server(paths: Paths) -> Any:
    return build_server(paths, encoder=FakeEncoder())


def test_the_server_exposes_exactly_search_fetch_and_coverage(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    names = {tool.name for tool in tools_of(a_server(paths))}

    assert names == {"search", "fetch", "coverage"}


def test_every_tool_describes_itself(tmp_path: Path) -> None:
    """A host agent picks tools by description; an empty one is unusable."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    for tool in tools_of(a_server(paths)):
        assert tool.description


def test_search_returns_passages_carrying_their_citation(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    hits = result_of(a_server(paths), "search", {"query": "mixture models"})

    assert hits
    assert hits[0]["citation"] == "bishop > 9. Mixture Models, pp. 10-14"
    assert hits[0]["book_slug"] == "bishop"
    assert "mixture models" in hits[0]["text"]


def test_search_scopes_to_one_course_when_asked(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    hits = result_of(
        a_server(paths), "search", {"query": "riemannian manifold", "course": "GI"}
    )

    assert hits
    assert all("GI" in hit["courses"] for hit in hits)


def test_search_honours_the_requested_number_of_passages(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    hits = result_of(a_server(paths), "search", {"query": "mixture models", "k": 1})

    assert len(hits) == 1


def test_search_for_a_course_with_no_material_returns_nothing(tmp_path: Path) -> None:
    """`EE` has no books. Silence is the honest answer, not a neighbour's."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    hits = result_of(
        a_server(paths), "search", {"query": "mixture models", "course": "EE"}
    )

    assert hits == []


def test_fetch_returns_the_section_and_its_neighbours(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    found = result_of(a_server(paths), "fetch", {"chunk_id": "p2"})

    assert found["chunk"]["chunk_id"] == "p2"
    assert found["previous"]["chunk_id"] == "p1"
    assert found["following"] is None


def test_fetching_an_unknown_id_is_an_error_not_an_empty_answer(
    tmp_path: Path,
) -> None:
    """A wrong id must not read as "no context exists here"."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    with pytest.raises(ToolError) as raised:
        call(a_server(paths), "fetch", {"chunk_id": "nope"})

    assert "nope" in str(raised.value)


def test_coverage_reports_every_course_including_the_empty_ones(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    courses = {
        entry["course"]: entry for entry in result_of(a_server(paths), "coverage")
    }

    assert len(courses) == 9
    assert courses["IAP"]["books"] == 1
    assert courses["IAP"]["indexed"] is True
    assert courses["EE"]["indexed"] is False


def test_loading_the_encoder_never_writes_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On stdio transport stdout is the wire; one stray print corrupts it."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    def chatty(_: Any) -> Any:
        print("downloading a 2.2 GB model")
        return FakeEncoder()

    server = build_server(paths, loader=chatty)
    result_of(server, "search", {"query": "mixture models"})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "downloading a 2.2 GB model" in captured.err


def test_the_encoder_is_loaded_once_not_per_query(tmp_path: Path) -> None:
    """BGE-M3 is 2.2 GB; reloading it per call would make the server unusable."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)
    encoder = FakeEncoder()
    loads = 0

    def load(_: Any) -> Any:
        nonlocal loads
        loads += 1
        return encoder

    server = build_server(paths, loader=load)
    result_of(server, "search", {"query": "mixture models"})
    result_of(server, "search", {"query": "gaussian"})

    assert loads == 1
