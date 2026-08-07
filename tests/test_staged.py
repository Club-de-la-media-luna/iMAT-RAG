from __future__ import annotations

import json
from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.catalogue import SourceTier
from imat_rag.ingest.staged import collect_staged, tier_of


def make_kb(root: Path, files: list[dict[str, object]]) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    for entry in files:
        target = root / str(entry["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4")
    (root / "intake.json").write_text(
        json.dumps({"archive": "TEST", "files": files}, ensure_ascii=False),
        encoding="utf-8",
    )
    return Paths(kb_root=root)


def an_entry(path: str, **over: object) -> dict[str, object]:
    course, _, kind, topic, _ = path.split("/")[1:]
    return {
        "path": path,
        "title": f"{course} · {topic}",
        "course": course,
        "kind": kind,
        "topic": topic,
        "sha256": "",
        "origin": "TEST/x",
        "classified": "test",
        **over,
    }


def test_every_kind_maps_onto_a_rung_of_the_ladder() -> None:
    """A kind with no tier would be filed and then silently never indexed."""
    for kind in ("slides", "exams", "assignments", "notes", "code"):
        assert isinstance(tier_of(kind), SourceTier), kind


def test_slides_outrank_books_and_notes_rank_below_them() -> None:
    """Student notes must never cite as confidently as a lecturer's deck."""
    assert tier_of("slides") > SourceTier.BASIC_BOOK
    assert tier_of("notes") < SourceTier.EXTRA_BOOK


def test_staged_material_is_discovered_from_the_intake_record(tmp_path: Path) -> None:
    """The ledgers describe books. Nothing describes a deck but intake.json."""
    paths = make_kb(
        tmp_path / "kb",
        [an_entry("courses/DRL/raw/slides/tema-1/repasorl.pdf")],
    )

    found = collect_staged(paths)

    assert [book.slug for book in found] == ["drl-slides-tema-1-repasorl"]
    assert found[0].courses == ("DRL",)
    assert found[0].tier == SourceTier.SLIDES


def test_slugs_stay_distinct_when_two_courses_use_the_same_filename(
    tmp_path: Path,
) -> None:
    """`hoja1.pdf` exists under several courses; one slug would overwrite another."""
    paths = make_kb(
        tmp_path / "kb",
        [
            an_entry("courses/GI/raw/exams/tema-1/hoja1.pdf"),
            an_entry("courses/MP/raw/exams/tema-1/hoja1.pdf"),
        ],
    )

    slugs = [book.slug for book in collect_staged(paths)]

    assert len(set(slugs)) == 2


def test_collecting_can_be_scoped_to_one_kind(tmp_path: Path) -> None:
    paths = make_kb(
        tmp_path / "kb",
        [
            an_entry("courses/DRL/raw/slides/tema-1/deck.pdf"),
            an_entry("courses/GI/raw/exams/tema-1/hoja1.pdf"),
        ],
    )

    found = collect_staged(paths, kinds=("slides",))

    assert [book.slug for book in found] == ["drl-slides-tema-1-deck"]


def test_only_pdfs_are_offered_to_the_extractor(tmp_path: Path) -> None:
    """mineru takes PDFs. A notebook needs a different path entirely."""
    paths = make_kb(
        tmp_path / "kb",
        [
            an_entry("courses/MGP/raw/code/t3/ffjord.ipynb"),
            an_entry("courses/DRL/raw/slides/tema-1/deck.pdf"),
        ],
    )

    found = collect_staged(paths)

    assert [book.path.suffix for book in found] == [".pdf"]


def test_an_entry_whose_file_has_gone_is_skipped(tmp_path: Path) -> None:
    """intake.json records what was taken, not what still exists."""
    paths = make_kb(tmp_path / "kb", [an_entry("courses/DRL/raw/slides/t/deck.pdf")])
    (paths.kb_root / "courses/DRL/raw/slides/t/deck.pdf").unlink()

    assert collect_staged(paths) == []


def test_a_knowledge_base_with_no_intake_record_yields_nothing(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")

    assert collect_staged(Paths(kb_root=root)) == []


def test_the_recorded_title_is_carried_onto_the_book(tmp_path: Path) -> None:
    """It is what a citation shows; a slug would read as gibberish."""
    paths = make_kb(
        tmp_path / "kb",
        [
            an_entry(
                "courses/DRL/raw/slides/tema-1/repasorl.pdf",
                title="DRL · Tema 1 · Repaso de RL",
            )
        ],
    )

    assert collect_staged(paths)[0].titles == ("DRL · Tema 1 · Repaso de RL",)
