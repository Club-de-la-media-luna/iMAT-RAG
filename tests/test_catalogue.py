from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.catalogue import Book, SourceTier, collect, parse_ledger, sha256_of

LEDGER = """\
# Literatura — Something

## Bibliografía Básica

### Murphy, K. P. — Probabilistic ML, Vol. 1 (2022)
- ES: ❌ not found
- EN: ✅ `raw/literature/murphy-vol-1.pdf`

### Koller, D. — PGM (2009)
- ES: ❌ not found
- EN: 🔗 link-only, unverified — https://example.org/pgm

## Bibliografía Complementaria

### Gelman, A. — BDA (2013)
- EN: ✅ `raw/literature/gelman-bda.pdf`

### Whittle, P. — Probability (2020)
- EN: ⬇ https://example.org/whittle.pdf
"""


def test_only_acquired_entries_are_kept() -> None:
    entries = parse_ledger(LEDGER, "IAP")

    assert [e.filename for e in entries] == ["murphy-vol-1.pdf", "gelman-bda.pdf"]


def test_bibliography_section_sets_the_tier() -> None:
    by_file = {e.filename: e for e in parse_ledger(LEDGER, "IAP")}

    assert by_file["murphy-vol-1.pdf"].tier is SourceTier.BASIC_BOOK
    assert by_file["gelman-bda.pdf"].tier is SourceTier.EXTRA_BOOK


def test_source_tiers_are_ordered_so_slides_outrank_books() -> None:
    assert SourceTier.SLIDES > SourceTier.EXAM > SourceTier.GUIDE
    assert SourceTier.GUIDE > SourceTier.BASIC_BOOK > SourceTier.EXTRA_BOOK


def test_entries_outside_a_known_section_are_ignored() -> None:
    stray = "### Loose, A. — Title\n- EN: ✅ `raw/literature/loose.pdf`\n"

    assert parse_ledger(stray, "IAP") == []


# --- collect over a fake knowledge base -------------------------------------


def make_kb(root: Path, ledgers: dict[str, str], pdfs: dict[str, list[str]]) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    for course, text in ledgers.items():
        course_dir = root / "courses" / course
        course_dir.mkdir(exist_ok=True)
        (course_dir / "literature.md").write_text(text, encoding="utf-8")
    for course, names in pdfs.items():
        lit = root / "courses" / course / "raw" / "literature"
        lit.mkdir(parents=True, exist_ok=True)
        for name in names:
            (lit / name).write_bytes(b"%PDF-1.4 fake")
    return Paths(kb_root=root)


SHARED = """\
## Bibliografía Básica

### Murphy, K. P. — Probabilistic ML, Vol. 1 (2022)
- EN: ✅ `raw/literature/murphy-vol-1.pdf`
"""


def test_a_book_listed_by_two_courses_becomes_one_record(tmp_path: Path) -> None:
    paths = make_kb(
        tmp_path,
        {"IAP": SHARED, "MGP": SHARED},
        {"IAP": ["murphy-vol-1.pdf"], "MGP": ["murphy-vol-1.pdf"]},
    )

    books = collect(paths)

    assert len(books) == 1
    assert books[0].courses == ("IAP", "MGP")
    assert books[0].slug == "murphy-vol-1"


def test_the_higher_tier_wins_when_courses_disagree(tmp_path: Path) -> None:
    complementary = SHARED.replace("Básica", "Complementaria")
    paths = make_kb(
        tmp_path,
        {"IAP": SHARED, "MGP": complementary},
        {"IAP": ["murphy-vol-1.pdf"], "MGP": ["murphy-vol-1.pdf"]},
    )

    books = collect(paths, tier=SourceTier.BASIC_BOOK)

    assert [b.slug for b in books] == ["murphy-vol-1"]
    assert collect(paths, tier=SourceTier.EXTRA_BOOK) == []


def test_entries_whose_file_is_missing_are_skipped(tmp_path: Path) -> None:
    paths = make_kb(tmp_path, {"IAP": SHARED}, {"IAP": []})

    assert collect(paths) == []


def test_collect_filters_by_requested_tier(tmp_path: Path) -> None:
    ledger = SHARED + (
        "\n## Bibliografía Complementaria\n\n"
        "### Gelman, A. — BDA (2013)\n"
        "- EN: ✅ `raw/literature/gelman-bda.pdf`\n"
    )
    paths = make_kb(
        tmp_path, {"IAP": ledger}, {"IAP": ["murphy-vol-1.pdf", "gelman-bda.pdf"]}
    )

    assert [b.slug for b in collect(paths, SourceTier.BASIC_BOOK)] == ["murphy-vol-1"]
    assert [b.slug for b in collect(paths, SourceTier.EXTRA_BOOK)] == ["gelman-bda"]


def test_sha256_identifies_content(tmp_path: Path) -> None:
    one = tmp_path / "a.pdf"
    two = tmp_path / "b.pdf"
    one.write_bytes(b"same")
    two.write_bytes(b"same")

    assert sha256_of(one) == sha256_of(two)
    assert len(sha256_of(one)) == 64


def test_books_are_hashable_and_comparable() -> None:
    book = Book(
        slug="x",
        path=Path("/x.pdf"),
        courses=("IAP",),
        titles=("X",),
        tier=SourceTier.BASIC_BOOK,
    )

    assert book.is_scan is False
    assert {book, book} == {book}
