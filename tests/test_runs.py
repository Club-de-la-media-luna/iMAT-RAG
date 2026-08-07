from __future__ import annotations

from imat_rag.ingest.chunk import chunk_book, merge_runs, split_sections

DECK = """# Deck

## Slide 1 — Motivation

Reinforcement learning needs a value function.

<!--page:1-->

## Slide 2 — Bellman

The Bellman equation relates a state to its successors.

<!--page:2-->

## Slide 3 — TD learning

Temporal difference learning updates towards a bootstrapped target.

<!--page:3-->

## Slide 4 — Q-learning

Q-learning is off-policy temporal difference control.

<!--page:4-->
"""


def test_a_deck_gives_one_section_per_slide() -> None:
    """The premise everything here rests on, kept honest by a test."""
    assert len(split_sections(DECK, "Deck")) >= 4


def test_merging_runs_gathers_consecutive_slides_under_one_budget() -> None:
    sections = split_sections(DECK, "Deck")

    merged = merge_runs(sections, budget=1000)

    assert len(merged) == 1
    assert "Bellman" in merged[0].text
    assert "Q-learning" in merged[0].text


def test_a_run_stops_at_its_budget_rather_than_swallowing_a_deck() -> None:
    sections = split_sections(DECK, "Deck")

    merged = merge_runs(sections, budget=25)

    assert len(merged) > 1


def test_a_merged_run_keeps_the_page_span_it_covers() -> None:
    """The citation says pp. 1-4; that is what tells a reader it is a run."""
    merged = merge_runs(split_sections(DECK, "Deck"), budget=1000)

    assert merged[0].pages == (0, 3)


def test_a_merged_run_is_named_for_where_it_starts() -> None:
    merged = merge_runs(split_sections(DECK, "Deck"), budget=1000)

    assert merged[0].breadcrumb.startswith("Deck")


def test_merging_nothing_yields_nothing() -> None:
    assert merge_runs([], budget=1000) == []


def test_chunking_by_run_makes_the_parent_bigger_than_its_children() -> None:
    """The whole point. A parent the size of its child expands to nothing."""
    chunks = chunk_book(DECK, "deck", book_title="Deck", run_tokens=1000)
    parents = [c for c in chunks if c.is_parent]
    children = [c for c in chunks if not c.is_parent]

    assert len(parents) == 1
    assert len(children) > 1
    assert parents[0].tokens > max(child.tokens for child in children)


def test_every_child_of_a_run_points_at_that_run() -> None:
    chunks = chunk_book(DECK, "deck", book_title="Deck", run_tokens=1000)
    parents = {c.chunk_id for c in chunks if c.is_parent}

    for child in (c for c in chunks if not c.is_parent):
        assert child.parent_id in parents


def test_without_a_run_budget_books_chunk_exactly_as_before() -> None:
    """Slides needed this; the forty-three books must not notice it exists."""
    assert chunk_book(DECK, "deck", book_title="Deck") == chunk_book(
        DECK, "deck", book_title="Deck", run_tokens=0
    )


def test_a_child_never_spans_two_slides_when_slides_are_small() -> None:
    """A child is the unit that matched. Merging slides into it blurs that."""
    chunks = chunk_book(DECK, "deck", book_title="Deck", run_tokens=1000)
    children = [c for c in chunks if not c.is_parent]

    for child in children:
        assert child.text.count("Slide ") <= 1
