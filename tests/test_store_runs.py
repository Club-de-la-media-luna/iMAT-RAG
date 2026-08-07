from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.catalogue import SourceTier
from imat_rag.ingest.extract import BookMeta
from imat_rag.ingest.store import ChunkConfig, chunk_extracted_book, read_chunks

BODY = (
    "The value function is estimated by bootstrapping from the successor "
    "state, which is what makes temporal difference learning different from "
    "Monte Carlo. Convergence needs a decaying step size and enough "
    "exploration to visit every state infinitely often in the limit. "
) * 2
"""About 110 tokens, which is the median slide measured on a real deck."""

DECK = "\n\n".join(
    f"<!--page:{n}-->\n\n## Diapositiva {n}\n\n{BODY} Slide {n}."
    for n in range(40)
)


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_meta(slug: str, tier: int) -> BookMeta:
    return BookMeta(
        slug=slug,
        courses=("DRL",),
        titles=("A source",),
        tier=tier,
        extraction_tier="born_digital",
        pages=40,
        page_span=(0, 39),
        source_sha256="f" * 64,
        source_path=f"/kb/{slug}.pdf",
        stage_key="0123456789abcdef",
        tool="mineru pipeline",
        figures=0,
        chars=len(DECK),
    )


def written(paths: Paths, slug: str, tier: int) -> tuple[int, int]:
    """Parents and the largest child, for one source at one tier."""
    paths.extracted.mkdir(parents=True, exist_ok=True)
    (paths.extracted / f"{slug}.md").write_text(DECK)
    chunk_extracted_book(paths, a_meta(slug, tier))
    chunks = list(read_chunks(paths, slug))
    parents = [c for c in chunks if c.is_parent]
    children = [c for c in chunks if not c.is_parent]
    return len(parents), max(c.tokens for c in children)


def test_a_deck_gets_parents_that_gather_several_slides(tmp_path: Path) -> None:
    """Forty slides must not become forty parents; that is not a parent."""
    paths = make_kb(tmp_path)

    parents, _ = written(paths, "a-deck", int(SourceTier.SLIDES))

    assert 1 < parents < 20


def test_a_decks_parent_is_much_larger_than_its_children(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    written(paths, "a-deck", int(SourceTier.SLIDES))

    chunks = list(read_chunks(paths, "a-deck"))
    biggest_parent = max(c.tokens for c in chunks if c.is_parent)
    biggest_child = max(c.tokens for c in chunks if not c.is_parent)

    assert biggest_parent > 3 * biggest_child


def test_a_book_is_chunked_exactly_as_it_always_was(tmp_path: Path) -> None:
    """Forty-three books are already indexed. Their chunk ids must not move."""
    paths = make_kb(tmp_path)

    parents, _ = written(paths, "a-book", int(SourceTier.BASIC_BOOK))

    assert parents == len([line for line in DECK.splitlines() if line.startswith("##")])


def test_every_staged_tier_gets_runs_not_only_slides(tmp_path: Path) -> None:
    """Exams and notes have the same shape problem decks do."""
    paths = make_kb(tmp_path)

    for tier in (SourceTier.EXAM, SourceTier.NOTES, SourceTier.ASSIGNMENT):
        parents, _ = written(paths, f"a-{tier.name.lower()}", int(tier))
        assert parents < 20, tier


def test_the_run_size_is_recorded_in_the_configuration() -> None:
    """It changes chunk boundaries, so the manifest has to carry it."""
    assert ChunkConfig().run_tokens > 0
