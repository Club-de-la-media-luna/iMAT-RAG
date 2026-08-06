from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from imat_rag.config import Paths
from imat_rag.inbox import (
    MINIMUM_PAGES,
    Drop,
    Rejected,
    SourceRepoIsPublic,
    add_entry,
    ingest,
    parse_drop,
    read_sources,
)

LEDGER = """\
# DRL — literatura

## Bibliografía básica

### Sutton, R. & Barto, A. — Reinforcement Learning (2018)
- EN: ✅ `sutton-barto-2018.pdf`

## Bibliografía complementaria

### Bertsekas, D. — Dynamic Programming (2012)
- EN: ⬇ pending
"""


class FakeRepoInfo:
    def __init__(self, private: bool) -> None:
        self.private = private


class FakeHub:
    """A source repository, described by the files it would hand over."""

    def __init__(self, tree: dict[str, str], private: bool = True) -> None:
        self.tree = tree
        self.private = private
        self.downloads: list[str] = []

    def repo_info(self, repo_id: str, **_: Any) -> FakeRepoInfo:
        return FakeRepoInfo(self.private)

    def snapshot_download(self, **kwargs: Any) -> str:
        self.downloads.append(str(kwargs.get("repo_id")))
        root = Path(str(kwargs["local_dir"]))
        for name, body in self.tree.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        return str(root)


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    for course in ("DRL", "IAP"):
        literature = root / "courses" / course / "raw" / "literature"
        literature.mkdir(parents=True)
        (root / "courses" / course / "literature.md").write_text(LEDGER)
    return Paths(kb_root=root)


def plenty_of_pages(_: Path) -> int:
    return 400


def ingest_from(
    paths: Paths, tree: dict[str, str], private: bool = True, **extra: Any
) -> Any:
    hub = FakeHub(tree, private=private)
    return ingest(
        paths, "someone/inbox", hub=hub, pages_of=extra.pop("pages_of", plenty_of_pages)
    )


# --- reading the drop path --------------------------------------------------


def test_the_folder_path_carries_the_course_and_the_kind() -> None:
    parsed = parse_drop("DRL/basic/sutton-barto-2018.pdf")

    assert parsed == Drop(course="DRL", kind="basic", filename="sutton-barto-2018.pdf")


def test_an_unknown_course_code_is_rejected_not_guessed() -> None:
    parsed = parse_drop("DEEPRL/basic/book.pdf")

    assert isinstance(parsed, Rejected)
    assert "DEEPRL" in parsed.reason


def test_an_unknown_kind_is_rejected() -> None:
    parsed = parse_drop("DRL/misc/book.pdf")

    assert isinstance(parsed, Rejected)


def test_a_file_dropped_at_the_top_level_is_rejected() -> None:
    """It is not lost, but nobody can tell which course it belongs to."""
    parsed = parse_drop("book.pdf")

    assert isinstance(parsed, Rejected)


def test_only_pdfs_are_taken() -> None:
    assert isinstance(parse_drop("DRL/basic/notes.docx"), Rejected)


def test_a_path_climbing_out_of_the_drop_is_rejected() -> None:
    """The tree comes from someone else's repository."""
    parsed = parse_drop("DRL/basic/../../../../etc/passwd.pdf")

    assert isinstance(parsed, Rejected)
    assert "path" in parsed.reason.lower()


# --- refusing an unsafe source ----------------------------------------------


def test_a_public_source_repository_is_refused(tmp_path: Path) -> None:
    """The mistake a contributor makes is leaving it public. Insist, don't ask."""
    paths = make_kb(tmp_path / "kb")

    with pytest.raises(SourceRepoIsPublic):
        ingest_from(paths, {"DRL/basic/book.pdf": "x"}, private=False)

    assert not list(paths.literature("DRL").glob("*.pdf"))


# --- taking material --------------------------------------------------------


def test_an_accepted_pdf_lands_in_the_course_literature_directory(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")

    report = ingest_from(paths, {"DRL/basic/silver-lectures.pdf": "%PDF-1.4"})

    assert (paths.literature("DRL") / "silver-lectures.pdf").is_file()
    assert [d.filename for d in report.accepted] == ["silver-lectures.pdf"]


def test_the_ledger_gains_an_entry_under_the_right_heading(tmp_path: Path) -> None:
    """A book with no ledger entry is invisible to the pipeline."""
    paths = make_kb(tmp_path / "kb")

    ingest_from(paths, {"DRL/basic/silver-lectures.pdf": "%PDF-1.4"})

    ledger = paths.ledger("DRL").read_text()
    basic, complementary = ledger.split("## Bibliografía complementaria")
    assert "silver-lectures.pdf" in basic
    assert "silver-lectures.pdf" not in complementary
    assert "✅" in basic


def test_a_complementary_drop_goes_under_the_complementary_heading(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")

    ingest_from(paths, {"DRL/extra/bertsekas-neuro.pdf": "%PDF-1.4"})

    _, complementary = (
        paths.ledger("DRL").read_text().split("## Bibliografía complementaria")
    )
    assert "bertsekas-neuro.pdf" in complementary


def test_a_sidecar_supplies_the_title_that_ends_up_in_citations(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")

    ingest_from(
        paths,
        {
            "DRL/basic/silver.pdf": "%PDF-1.4",
            "DRL/basic/silver.txt": "Silver, D. — Reinforcement Learning (2015)\n",
        },
    )

    assert (
        "Silver, D. — Reinforcement Learning (2015)" in paths.ledger("DRL").read_text()
    )


def test_without_a_sidecar_the_title_comes_from_the_filename(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")

    ingest_from(paths, {"DRL/basic/silver-lectures-2015.pdf": "%PDF-1.4"})

    assert "Silver Lectures 2015" in paths.ledger("DRL").read_text()


# --- not taking material twice ----------------------------------------------


def test_a_book_already_in_the_corpus_is_skipped(tmp_path: Path) -> None:
    """Content hash, not filename: the same book renamed is still the same book."""
    paths = make_kb(tmp_path / "kb")
    (paths.literature("DRL") / "already-here.pdf").write_text("%PDF-1.4 identical")

    report = ingest_from(paths, {"DRL/basic/renamed.pdf": "%PDF-1.4 identical"})

    assert [d.filename for d in report.duplicates] == ["renamed.pdf"]
    assert not (paths.literature("DRL") / "renamed.pdf").exists()


def test_ingesting_the_same_repository_twice_changes_nothing(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    tree = {"DRL/basic/silver.pdf": "%PDF-1.4"}

    ingest_from(paths, tree)
    first = paths.ledger("DRL").read_text()
    ingest_from(paths, tree)

    assert paths.ledger("DRL").read_text() == first


# --- refusing material that would lie about coverage ------------------------


def test_a_truncated_front_matter_pdf_is_rejected(tmp_path: Path) -> None:
    """Two ledger entries are already wrong this way; they are worse than a gap."""
    paths = make_kb(tmp_path / "kb")

    report = ingest_from(
        paths, {"DRL/basic/preview.pdf": "%PDF-1.4"}, pages_of=lambda _: 4
    )

    assert report.accepted == []
    assert any("page" in r.reason.lower() for r in report.rejected)
    assert not (paths.literature("DRL") / "preview.pdf").exists()
    assert MINIMUM_PAGES > 4


# --- kinds that are stored but not yet ingestable ---------------------------


def test_slides_are_kept_but_get_no_ledger_entry(tmp_path: Path) -> None:
    """Nothing parses the slides tier yet; claiming otherwise would be a lie."""
    paths = make_kb(tmp_path / "kb")

    report = ingest_from(
        paths, {"DRL/slides/tema-3.pdf": "%PDF-1.4"}, pages_of=lambda _: 30
    )

    assert (
        paths.kb_root / "courses" / "DRL" / "raw" / "slides" / "tema-3.pdf"
    ).is_file()
    assert "tema-3" not in paths.ledger("DRL").read_text()
    assert [d.filename for d in report.stored] == ["tema-3.pdf"]


# --- remembering where material comes from ----------------------------------


def test_ingesting_registers_the_source_repository(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")

    ingest_from(paths, {"DRL/basic/silver.pdf": "%PDF-1.4"})

    assert read_sources(paths) == ["someone/inbox"]


def test_a_source_is_registered_once_however_often_it_is_pulled(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")

    ingest_from(paths, {"DRL/basic/silver.pdf": "%PDF-1.4"})
    ingest_from(paths, {"DRL/basic/silver.pdf": "%PDF-1.4"})

    assert read_sources(paths) == ["someone/inbox"]


# --- writing ledger entries -------------------------------------------------


def test_an_entry_is_appended_to_the_end_of_its_section() -> None:
    updated = add_entry(LEDGER, "Bibliografía básica", "A Title", "a-title.pdf")

    basic = updated.split("## Bibliografía complementaria")[0]
    assert basic.index("Sutton") < basic.index("A Title")


def test_a_missing_section_is_created_rather_than_dropped() -> None:
    updated = add_entry("# IAP\n", "Bibliografía básica", "A Title", "a.pdf")

    assert "## Bibliografía básica" in updated
    assert "a.pdf" in updated
