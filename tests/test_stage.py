from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.catalogue import sha256_of
from imat_rag.ingest.stage import (
    Named,
    Unreadable,
    parse_filename,
    sort_into,
    take,
)
from imat_rag.ingest.staged import read_intake


def test_a_name_says_course_kind_topic_and_title() -> None:
    """The flat inbox carries no directories, so the name is the whole address."""
    named = parse_filename("mgp_slides_teoria_dgm-08-agent-eval.pdf")

    assert isinstance(named, Named)
    assert named.course == "MGP"
    assert named.kind == "slides"
    assert named.topic == "teoria"
    assert named.stem == "dgm-08-agent-eval"


def test_a_name_missing_its_kind_is_refused_rather_than_guessed() -> None:
    """`mgp_tema1_x` has no tier, and a guessed tier corrupts every ranking."""
    refused = parse_filename("mgp_tema1_repaso.pdf")

    assert isinstance(refused, Unreadable)
    assert "kind" in refused.reason


def test_a_named_download_is_sorted_to_the_path_the_pipeline_reads(
    tmp_path: Path,
) -> None:
    """The staging tree mirrors the corpus, so taking it in is a plain copy."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "mgp_slides_teoria_dgm-08-agent-eval.pdf").write_bytes(b"%PDF-1.4 a")

    report = sort_into(inbox, tmp_path / "staged")

    landed = tmp_path / "staged" / "courses/MGP/raw/slides/teoria/dgm-08-agent-eval.pdf"
    assert landed.is_file()
    assert [named.stem for named in report.sorted] == ["dgm-08-agent-eval"]


def test_a_badly_named_download_is_left_where_it_is(tmp_path: Path) -> None:
    """A refusal must leave the file in the inbox to be renamed and re-run."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "mgp_tema1_repaso.pdf").write_bytes(b"%PDF-1.4 b")

    report = sort_into(inbox, tmp_path / "staged")

    assert (inbox / "mgp_tema1_repaso.pdf").is_file()
    assert [bad.filename for bad in report.unreadable] == ["mgp_tema1_repaso.pdf"]
    assert not report.sorted


def test_sorting_twice_does_not_duplicate_what_is_already_staged(
    tmp_path: Path,
) -> None:
    """Re-running after renaming one file must not re-report the rest."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "ee_slides_xai_8-fairness.pdf").write_bytes(b"%PDF-1.4 c")

    first = sort_into(inbox, tmp_path / "staged")
    second = sort_into(inbox, tmp_path / "staged")

    assert len(first.sorted) == 1
    assert not second.sorted
    assert [already.stem for already in second.already] == ["8-fairness"]


def a_corpus(root: Path) -> Paths:
    """An empty knowledge base, with nothing taken in yet."""
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def staged_pdf(staging: Path, relative: str, body: bytes) -> Path:
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return target


def test_taking_a_staged_file_files_it_and_records_it_in_the_intake(
    tmp_path: Path,
) -> None:
    """Nothing but intake.json tells the pipeline a deck exists."""
    paths = a_corpus(tmp_path / "kb")
    staging = tmp_path / "staged"
    staged_pdf(
        staging,
        "courses/MGP/raw/slides/teoria/dgm-08-agent-eval.pdf",
        b"%PDF-1.4 agentic",
    )

    report = take(paths, staging, pages_of=lambda _: 34)

    filed = paths.kb_root / "courses/MGP/raw/slides/teoria/dgm-08-agent-eval.pdf"
    assert filed.is_file()
    entry = read_intake(paths)[0]
    assert entry["path"] == "courses/MGP/raw/slides/teoria/dgm-08-agent-eval.pdf"
    assert entry["course"] == "MGP"
    assert entry["kind"] == "slides"
    assert entry["topic"] == "teoria"
    assert entry["pages"] == 34
    assert entry["sha256"] == sha256_of(filed)
    assert len(report.taken) == 1


def test_a_file_the_corpus_already_holds_is_not_taken_twice(tmp_path: Path) -> None:
    """M9 found 23 byte-identical copies in one drop; a re-download is the same."""
    paths = a_corpus(tmp_path / "kb")
    staging = tmp_path / "staged"
    staged_pdf(staging, "courses/EE/raw/slides/xai/8-fairness.pdf", b"%PDF-1.4 same")
    staged_pdf(
        staging, "courses/EE/raw/slides/xai/8-fairness-copy.pdf", b"%PDF-1.4 same"
    )

    report = take(paths, staging, pages_of=lambda _: 12)

    assert len(report.taken) == 1
    assert len(report.duplicates) == 1
    assert len(read_intake(paths)) == 1


def test_taking_twice_leaves_one_intake_entry(tmp_path: Path) -> None:
    """`take` is meant to be safe to re-run after fixing one bad name."""
    paths = a_corpus(tmp_path / "kb")
    staging = tmp_path / "staged"
    staged_pdf(staging, "courses/MP/raw/notes/tema-3/beta.pdf", b"%PDF-1.4 mp")

    take(paths, staging, pages_of=lambda _: 8)
    second = take(paths, staging, pages_of=lambda _: 8)

    assert len(read_intake(paths)) == 1
    assert not second.taken


def test_an_entry_carries_a_title_a_reader_can_cite(tmp_path: Path) -> None:
    """The title is what a search result shows; a slug is not a citation."""
    paths = a_corpus(tmp_path / "kb")
    staging = tmp_path / "staged"
    staged_pdf(
        staging, "courses/MGP/raw/slides/teoria/dgm-08-agent-eval.pdf", b"%PDF-1.4 t"
    )

    take(paths, staging, pages_of=lambda _: 34)

    assert read_intake(paths)[0]["title"] == "MGP · Teoria · Dgm 08 Agent Eval"
