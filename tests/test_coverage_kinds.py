from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.coverage import coverage
from imat_rag.ingest.catalogue import SourceTier
from imat_rag.ingest.extract import BookMeta


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_source(paths: Paths, slug: str, course: str, tier: int) -> None:
    meta = BookMeta(
        slug=slug,
        courses=(course,),
        titles=(slug,),
        tier=tier,
        extraction_tier="born_digital",
        pages=10,
        page_span=(0, 9),
        source_sha256="0" * 64,
        source_path=f"/kb/{slug}.pdf",
        stage_key="k",
        tool="mineru",
        figures=0,
        chars=100,
    )
    paths.extracted.mkdir(parents=True, exist_ok=True)
    (paths.extracted / f"{slug}.meta.json").write_text(
        meta.model_dump_json(), encoding="utf-8"
    )


def test_coverage_says_what_kind_of_material_a_course_has(tmp_path: Path) -> None:
    """"30 sources" is not an answer when 15 of them are lab sheets."""
    paths = make_kb(tmp_path / "kb")
    a_source(paths, "a-deck", "IM", int(SourceTier.SLIDES))
    a_source(paths, "b-deck", "IM", int(SourceTier.SLIDES))
    a_source(paths, "a-sheet", "IM", int(SourceTier.ASSIGNMENT))
    a_source(paths, "a-book", "IM", int(SourceTier.BASIC_BOOK))

    found = {entry.course: entry for entry in coverage(paths)}["IM"]

    assert found.by_kind == {"basic book": 1, "slides": 2, "assignment": 1}


def test_a_course_with_nothing_reports_no_kinds(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")

    found = {entry.course: entry for entry in coverage(paths)}["EE"]

    assert found.by_kind == {}
    assert found.indexed is False
