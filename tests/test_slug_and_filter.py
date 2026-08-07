from __future__ import annotations

from imat_rag.index.lance import course_filter
from imat_rag.ingest.staged import slug_for


def test_slugs_already_in_the_index_do_not_move() -> None:
    """190 sources are extracted under these names; changing them re-does it all."""
    assert (
        slug_for("courses/DRL/raw/slides/tema-1/1-repasorl-1a.pdf")
        == "drl-slides-tema-1-1-repasorl-1a"
    )
    assert slug_for("courses/GI/raw/exams/tema-1/hoja1.pdf") == "gi-exams-tema-1-hoja1"


def test_two_files_in_different_directories_never_share_a_slug() -> None:
    """A project arrives with its own tree; publish already carries four levels."""
    first = slug_for("courses/MGP/raw/code/t3/a/fig.pdf")
    second = slug_for("courses/MGP/raw/code/t3/b/fig.pdf")

    assert first != second


def test_a_shallow_path_does_not_leak_its_extension_into_the_slug() -> None:
    """The slug names the extracted Markdown; `.pdf` in it would be absurd."""
    assert ".pdf" not in slug_for("courses/DRL/raw/slides/deck.pdf")


def test_a_path_too_short_to_read_is_not_fatal() -> None:
    """One malformed intake entry must not abort discovery of the other 189."""
    assert slug_for("courses/DRL/raw/deck.pdf") == "drl-deck"


def test_the_course_filter_cannot_be_talked_out_of_scoping() -> None:
    """The MCP tool hands this string straight from a host agent."""
    predicate = course_filter("x' OR '1'='1")

    assert "OR '1'='1'" not in predicate
    assert predicate.count("'") == 2


def test_a_quote_in_a_course_cannot_break_the_predicate() -> None:
    assert course_filter("G'I").count("'") == 2


def test_a_real_course_still_filters() -> None:
    assert course_filter("GI") == "courses LIKE '%GI%'"
