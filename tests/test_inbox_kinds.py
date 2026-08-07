from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.inbox import Report, _held_already, _take


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    for course in ("GI", "IAP", "MGP"):
        (root / "courses" / course).mkdir(parents=True, exist_ok=True)
    return Paths(kb_root=root)


def a_drop(root: Path, relative: str, body: bytes = b"%PDF-1.4 one") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


def run(paths: Paths, root: Path, pages: int = 4) -> Report:
    report = Report(repo_id="someone/drop")
    _take(paths, root, report, _held_already(paths), lambda _: pages)
    return report


def test_a_four_page_exam_sheet_is_not_front_matter(tmp_path: Path) -> None:
    """The page floor exists to catch truncated book previews.

    Applied to every kind it rejects most of what a course actually sets:
    115 of the 217 files in the first real drop are under twenty pages.
    """
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "GI/exams/hoja1.pdf")

    report = run(paths, root)

    assert [d.filename for d in report.stored] == ["hoja1.pdf"]
    assert report.rejected == []


def test_a_four_page_book_is_still_front_matter(tmp_path: Path) -> None:
    """The floor still does its job where it was aimed."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "GI/basic/a-book.pdf")

    report = run(paths, root)

    assert report.accepted == []
    assert "pages" in report.rejected[0].reason


def test_material_already_stored_is_not_taken_twice(tmp_path: Path) -> None:
    """`_held_already` only looked at literature/, so decks re-copied forever."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "GI/slides/deck.pdf")
    run(paths, root)

    second = run(paths, root)

    assert second.stored == []
    assert [d.filename for d in second.duplicates] == ["deck.pdf"]


def test_a_book_dropped_for_a_second_course_still_gets_its_ledger_entry(
    tmp_path: Path,
) -> None:
    """Murphy is listed by IAP and MGP. The second must not lose its entry."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "IAP/basic/murphy.pdf")
    a_drop(root, "MGP/basic/murphy.pdf")

    run(paths, root, pages=800)

    assert "murphy.pdf" in paths.ledger("IAP").read_text(encoding="utf-8")
    assert "murphy.pdf" in paths.ledger("MGP").read_text(encoding="utf-8")


def test_a_ledger_entry_is_not_written_twice_on_a_rerun(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "IAP/basic/murphy.pdf")
    run(paths, root, pages=800)

    run(paths, root, pages=800)

    assert paths.ledger("IAP").read_text(encoding="utf-8").count("murphy.pdf") == 1


def test_one_unreadable_pdf_does_not_abandon_the_drop(tmp_path: Path) -> None:
    """Elsewhere the codebase is explicit that one bad file must not stop a run."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "GI/slides/broken.pdf", b"not a pdf")
    a_drop(root, "GI/slides/fine.pdf")

    def pages(path: Path) -> int:
        if "broken" in path.name:
            raise RuntimeError("cannot open")
        return 30

    report = Report(repo_id="someone/drop")
    _take(paths, root, report, _held_already(paths), pages)

    assert [d.filename for d in report.stored] == ["fine.pdf"]
    assert [r.path for r in report.rejected] == ["GI/slides/broken.pdf"]
