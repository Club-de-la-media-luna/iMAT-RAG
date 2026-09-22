from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.inbox import Report, _held_already, _take
from imat_rag.ingest.staged import collect_staged, read_intake


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_drop(root: Path, relative: str, body: bytes = b"%PDF-1.4 one") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


def run(paths: Paths, root: Path, pages: int = 40) -> Report:
    report = Report(repo_id="someone/drop")
    _take(paths, root, report, _held_already(paths), lambda _: pages)
    return report


def test_a_stored_deck_is_recorded_in_the_intake(tmp_path: Path) -> None:
    """Copied and unrecorded is a silent dead drop: the file is in the corpus,
    nothing discovers it, and `rag coverage` reports the course as it was."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "MGP/slides/dgm-08-agent-eval.pdf")

    run(paths, root)

    assert [entry["path"] for entry in read_intake(paths)] == [
        "courses/MGP/raw/slides/general/dgm-08-agent-eval.pdf"
    ]
    assert [book.slug for book in collect_staged(paths)] == [
        "mgp-slides-general-dgm-08-agent-eval"
    ]


def test_an_assignment_is_a_kind_the_inbox_knows(tmp_path: Path) -> None:
    """`staged.TIERS` ranks assignments, notes and code; the inbox refused all
    three, so the one tier a course sets work under could never arrive."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "MGP/assignments/practica-agentes.pdf")

    report = run(paths, root)

    assert [drop.filename for drop in report.stored] == ["practica-agentes.pdf"]
    assert not report.rejected


def test_a_drop_may_name_its_topic(tmp_path: Path) -> None:
    """A course sets work per topic, and `general` for everything loses that."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "MGP/slides/teoria/dgm-08-agent-eval.pdf")

    run(paths, root)

    assert [entry["topic"] for entry in read_intake(paths)] == ["teoria"]


def test_taking_the_same_drop_twice_records_it_once(tmp_path: Path) -> None:
    """`rag inbox` is re-run whenever a contributor adds one more file."""
    paths = make_kb(tmp_path / "kb")
    root = tmp_path / "drop"
    a_drop(root, "MGP/slides/teoria/dgm-08-agent-eval.pdf")

    run(paths, root)
    run(paths, root)

    assert len(read_intake(paths)) == 1
