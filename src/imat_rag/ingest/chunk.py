"""Split extracted Markdown into the units that get embedded and returned.

Two tiers. Child chunks are small and carry the embeddings, because a precise
query should match a precise passage. Parent chunks are whole sections and are
what actually comes back, because an answer about EM is useless if the
derivation is cut in half.

Every chunk is prefixed with its breadcrumb. Mathematical notation is defined
once per chapter and used for forty pages, so a chunk that says "substituting
(9.14) into (9.11) gives" means nothing without knowing it is Bishop chapter 9.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence

from pydantic import BaseModel, Field

PAGE_ANCHOR = re.compile(r"<!--page:(\d+)-->")
INLINE_SCRIPT = re.compile(r"</?su[bp]>", re.IGNORECASE)
"""mineru sprinkles <sub>/<sup> inside ordinary words.

It renders "diagonalising" as "di<sub>agona</sub>li<sub>s</sub>i<sub>ng</sub>",
which breaks the word for both a reader and a tokenizer. Real subscripts in this
corpus live inside LaTeX, so unwrapping these tags loses nothing.
"""
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")

CHARS_PER_TOKEN = 4
"""Rough conversion used for budgeting.

The real tokenizer arrives with the embedding model. Chunk sizes are targets,
not limits — BGE-M3 accepts 8192 tokens, so an estimate that is off by a third
costs nothing, and avoiding the dependency keeps chunking testable in
milliseconds.
"""

ATOMIC_PREFIXES = ("$$", "|", "![", "<table", "```")
"""Blocks that lose their meaning if cut: equations, tables, figures, code."""

CHILD_TOKENS = 350
PARENT_TOKENS = 2000


def estimate_tokens(text: str) -> int:
    """Approximate token count for budgeting."""
    return max(1, len(text) // CHARS_PER_TOKEN)


class Piece(BaseModel, frozen=True):
    """An atomic run of Markdown that must never be split.

    Equations, tables and figures are indivisible: half a derivation is not
    half as useful, it is useless. Paragraphs are divisible but are the
    smallest unit worth moving.
    """

    text: str
    page: int
    atomic: bool = False


class Chunk(BaseModel, frozen=True):
    """A retrievable unit of one book."""

    chunk_id: str
    book_slug: str
    breadcrumb: str
    text: str
    page_start: int
    page_end: int
    parent_id: str = ""
    is_parent: bool = False
    tokens: int = 0
    courses: tuple[str, ...] = ()
    source_tier: int = 0
    content_types: tuple[str, ...] = Field(default=())

    @property
    def embedding_text(self) -> str:
        """What actually gets embedded: the breadcrumb, then the body."""
        return f"{self.breadcrumb}\n\n{self.text}" if self.breadcrumb else self.text


def chunk_id(
    book_slug: str,
    page_start: int,
    page_end: int,
    text: str,
    is_parent: bool = False,
) -> str:
    """Content-addressed identifier.

    Derived from content alone, never from insertion order, so two people
    ingesting the same material independently produce identical ids and the
    union of their work is the correct result with no deduplication pass.

    The tier is part of the address because a section short enough to yield a
    single child gives that child the same text and pages as its parent. Without
    this they collide, and a child would end up pointing at itself.
    """
    tier = "parent" if is_parent else "child"
    payload = f"{book_slug}:{tier}:{page_start}-{page_end}:{text}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def split_pieces(markdown: str) -> list[Piece]:
    """Break Markdown into atomic and divisible pieces, tracking the page."""
    pieces: list[Piece] = []
    page = 0
    for block in re.split(r"\n{2,}", markdown):
        block = block.strip()
        if not block:
            continue
        if anchors := PAGE_ANCHOR.findall(block):
            page = int(anchors[-1])
            block = PAGE_ANCHOR.sub("", block).strip()
            if not block:
                continue
        atomic = _is_atomic(block)
        if not atomic:
            block = INLINE_SCRIPT.sub("", block)
        pieces.append(Piece(text=block, page=page, atomic=atomic))
    return pieces


def _is_atomic(block: str) -> bool:
    """Whether a block must survive intact."""
    return block.startswith(ATOMIC_PREFIXES)


class Section(BaseModel, frozen=True):
    """A run of content under one heading path."""

    breadcrumb: str
    pieces: tuple[Piece, ...]

    @property
    def text(self) -> str:
        """The section's content, pieces rejoined."""
        return "\n\n".join(piece.text for piece in self.pieces)

    @property
    def pages(self) -> tuple[int, int]:
        """First and last source page this section covers."""
        pages = [piece.page for piece in self.pieces]
        return (min(pages), max(pages)) if pages else (0, 0)


def split_sections(markdown: str, book_title: str = "") -> list[Section]:
    """Walk the heading tree, yielding one Section per heading path."""
    trail: list[str] = []
    pieces: list[Piece] = []
    sections: list[Section] = []

    def flush() -> None:
        if pieces:
            sections.append(
                Section(
                    breadcrumb=" > ".join(filter(None, [book_title, *trail])),
                    pieces=tuple(pieces),
                )
            )
            pieces.clear()

    for piece in split_pieces(markdown):
        heading = HEADING.match(piece.text)
        if not heading:
            pieces.append(piece)
            continue
        flush()
        depth = len(heading.group("hashes"))
        del trail[depth - 1 :]
        trail.append(heading.group("title"))

    flush()
    return sections


def _pack(pieces: Sequence[Piece], budget: int) -> Iterator[list[Piece]]:
    """Group pieces into runs under a token budget, never splitting an atom."""
    current: list[Piece] = []
    used = 0
    for piece in pieces:
        cost = estimate_tokens(piece.text)
        if current and used + cost > budget:
            yield current
            current, used = [], 0
        current.append(piece)
        used += cost
    if current:
        yield current


def merge_runs(sections: Sequence[Section], budget: int) -> list[Section]:
    """Gather consecutive sections into runs of roughly `budget` tokens.

    A book's section is a chapter subsection and already the right size to be a
    parent. A deck's section is one slide — forty tokens, sometimes eleven — and
    a parent that size expands to nothing, which defeats the point of having
    parents at all. Merging first gives the reader the surrounding argument.

    Runs are named for where they start. What tells a reader they are looking
    at a span rather than a single slide is the page range on the citation.
    """
    return [_joined(run) for run in _runs_of(sections, budget)]


def _joined(sections: Sequence[Section]) -> Section:
    """One section covering everything its parts covered."""
    if len(sections) == 1:
        return sections[0]
    return Section(
        breadcrumb=sections[0].breadcrumb,
        pieces=tuple(piece for section in sections for piece in section.pieces),
    )


def chunk_run(
    sections: Sequence[Section],
    book_slug: str,
    child_tokens: int = CHILD_TOKENS,
) -> list[Chunk]:
    """One parent spanning several sections, with a child per section.

    The child stays the unit that matched. Packing slides together into a
    child would blur which one the query actually hit, and the child is the
    only thing the index ever compares against.
    """
    run = _joined(sections)
    parent = _make_chunk(run.pieces, run.breadcrumb, book_slug, is_parent=True)
    chunks = [parent]
    for section in sections:
        chunks.extend(
            _make_chunk(
                child_pieces,
                section.breadcrumb,
                book_slug,
                parent_id=parent.chunk_id,
            )
            for child_pieces in _pack(section.pieces, child_tokens)
        )
    return chunks


def chunk_section(
    section: Section,
    book_slug: str,
    child_tokens: int = CHILD_TOKENS,
    parent_tokens: int = PARENT_TOKENS,
) -> list[Chunk]:
    """Turn one section into its parent chunks and their children."""
    chunks: list[Chunk] = []
    for parent_pieces in _pack(section.pieces, parent_tokens):
        parent = _make_chunk(
            parent_pieces, section.breadcrumb, book_slug, is_parent=True
        )
        chunks.append(parent)
        chunks.extend(
            _make_chunk(
                child_pieces,
                section.breadcrumb,
                book_slug,
                parent_id=parent.chunk_id,
            )
            for child_pieces in _pack(parent_pieces, child_tokens)
        )
    return chunks


def _make_chunk(
    pieces: Sequence[Piece],
    breadcrumb: str,
    book_slug: str,
    parent_id: str = "",
    is_parent: bool = False,
) -> Chunk:
    text = "\n\n".join(piece.text for piece in pieces)
    pages = [piece.page for piece in pieces]
    start, end = (min(pages), max(pages)) if pages else (0, 0)
    return Chunk(
        chunk_id=chunk_id(book_slug, start, end, text, is_parent),
        book_slug=book_slug,
        breadcrumb=breadcrumb,
        text=text,
        page_start=start,
        page_end=end,
        parent_id=parent_id,
        is_parent=is_parent,
        tokens=estimate_tokens(text),
        content_types=tuple(
            sorted({"atomic" if piece.atomic else "prose" for piece in pieces})
        ),
    )


def chunk_book(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    markdown: str,
    book_slug: str,
    book_title: str = "",
    courses: tuple[str, ...] = (),
    source_tier: int = 0,
    run_tokens: int = 0,
) -> list[Chunk]:
    """Chunk one extracted source.

    `run_tokens` switches on the slide path: consecutive sections are gathered
    into a parent of about that size, each section becoming one child. Left at
    zero, every section is its own parent, which is what a book wants and what
    the forty-three already in the index were built with.
    """
    sections = split_sections(markdown, book_title)
    produced: list[Chunk] = []
    if run_tokens:
        for run in _runs_of(sections, run_tokens):
            produced.extend(chunk_run(run, book_slug))
    else:
        for section in sections:
            produced.extend(chunk_section(section, book_slug))

    return [
        chunk.model_copy(update={"courses": courses, "source_tier": source_tier})
        for chunk in produced
    ]


def _runs_of(sections: Sequence[Section], budget: int) -> Iterator[list[Section]]:
    """The same grouping `merge_runs` does, kept as its parts."""
    current: list[Section] = []
    used = 0
    for section in sections:
        cost = estimate_tokens(section.text)
        if current and used + cost > budget:
            yield current
            current, used = [], 0
        current.append(section)
        used += cost
    if current:
        yield current
