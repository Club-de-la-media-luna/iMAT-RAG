from __future__ import annotations

from pathlib import Path
from typing import Any

from imat_rag.config import Paths
from imat_rag.coverage import COURSE_NAMES, coverage
from imat_rag.ingest.extract import BookMeta
from imat_rag.ingest.store import BookChunks, Manifest, write_manifest


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_book(paths: Paths, slug: str, courses: tuple[str, ...], **extra: Any) -> BookMeta:
    fields: dict[str, Any] = {
        "slug": slug,
        "courses": courses,
        "titles": (slug,),
        "tier": 2,
        "extraction_tier": "prose",
        "pages": 100,
        "page_span": (1, 100),
        "source_sha256": "0" * 64,
        "source_path": f"/books/{slug}.pdf",
        "stage_key": "abcd1234",
        "tool": "mineru",
        "figures": 0,
        "chars": 1000,
    }
    fields.update(extra)
    meta = BookMeta(**fields)
    paths.extracted.mkdir(parents=True, exist_ok=True)
    (paths.extracted / f"{slug}.meta.json").write_text(
        meta.model_dump_json(), encoding="utf-8"
    )
    return meta


def seed(paths: Paths) -> None:
    a_book(paths, "bishop", ("IAP", "MGP"), pages=750)
    a_book(paths, "do-carmo", ("GI",), pages=300)
    write_manifest(
        paths,
        Manifest(
            books=[
                BookChunks(
                    slug="bishop",
                    source_sha256="0" * 64,
                    stage_key="abcd1234",
                    chunks=400,
                    parents=100,
                    children=300,
                    courses=("IAP", "MGP"),
                ),
                BookChunks(
                    slug="do-carmo",
                    source_sha256="0" * 64,
                    stage_key="abcd1234",
                    chunks=150,
                    parents=50,
                    children=100,
                    courses=("GI",),
                ),
            ]
        ),
    )


def test_coverage_reports_every_course_even_the_empty_ones(tmp_path: Path) -> None:
    """A course with nothing indexed must still appear, or its hole is invisible."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    reported = {entry.course for entry in coverage(paths)}

    assert reported == set(COURSE_NAMES)


def test_coverage_counts_books_pages_and_chunks_per_course(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    by_course = {entry.course: entry for entry in coverage(paths)}

    assert by_course["IAP"].books == 1
    assert by_course["IAP"].pages == 750
    assert by_course["IAP"].chunks == 400
    assert by_course["GI"].pages == 300


def test_a_book_shared_by_two_courses_counts_for_both(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    by_course = {entry.course: entry for entry in coverage(paths)}

    assert by_course["MGP"].books == 1
    assert by_course["MGP"].book_slugs == ("bishop",)
    assert by_course["IAP"].book_slugs == ("bishop",)


def test_a_course_with_no_material_reports_zeroes_and_is_not_indexed(
    tmp_path: Path,
) -> None:
    """`EE` has nothing. The system says so rather than answering from elsewhere."""
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    empty = next(entry for entry in coverage(paths) if entry.course == "EE")

    assert empty.books == 0
    assert empty.pages == 0
    assert empty.chunks == 0
    assert empty.indexed is False
    assert empty.name == COURSE_NAMES["EE"]


def test_coverage_is_ordered_by_course_code(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    seed(paths)

    codes = [entry.course for entry in coverage(paths)]

    assert codes == sorted(codes)


def test_coverage_of_an_empty_knowledge_base_is_all_holes(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")

    entries = coverage(paths)

    assert len(entries) == len(COURSE_NAMES)
    assert all(not entry.indexed for entry in entries)
