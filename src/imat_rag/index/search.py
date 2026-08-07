"""Build the index, and search it.

Retrieval is hybrid — dense vectors and BM25 fused by reciprocal rank — then
every matched child is expanded to its parent section before returning. The
child is what matched; the parent is what is worth reading. No reranker in v1;
see ADR and the design's deferred list.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

from pydantic import BaseModel, computed_field

from imat_rag.config import Paths
from imat_rag.index import lance
from imat_rag.index.embed import (
    EmbedConfig,
    Encoder,
    batched,
    encode_texts,
    load_encoder,
)
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.store import locate_chunk, read_chunks, read_manifest


class Hit(BaseModel):
    """One retrieved passage, with everything a citation needs."""

    chunk_id: str
    book_slug: str
    breadcrumb: str
    text: str
    page_start: int
    page_end: int
    courses: tuple[str, ...]
    score: float
    matched_text: str = ""
    """The child that matched, when the returned text is its parent."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def citation(self) -> str:
        """Human-readable source, e.g. `Bishop PRML > 9.4, pp. 439-441`.

        Computed rather than plain so that it survives serialisation: an MCP
        client receives the citation with the passage, not the pieces to
        reassemble it from.
        """
        pages = (
            f"p. {self.page_start}"
            if self.page_start == self.page_end
            else f"pp. {self.page_start}-{self.page_end}"
        )
        return f"{self.breadcrumb}, {pages}"


class Neighbourhood(BaseModel):
    """One chunk and the sections either side of it, for following context."""

    chunk: Hit
    previous: Hit | None = None
    following: Hit | None = None


def all_chunks(paths: Paths) -> Iterator[Chunk]:
    """Every chunk currently recorded in the manifest."""
    for book in read_manifest(paths).books:
        yield from read_chunks(paths, book.slug)


def build(
    paths: Paths,
    config: EmbedConfig | None = None,
    encoder: Encoder | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """Embed every child and write both tables. Returns (children, parents).

    Parents are stored without vectors: they are never matched, only fetched
    once a child has won, so embedding them would be wasted work and disk.
    """
    config = config or EmbedConfig()
    chunks = list(all_chunks(paths))
    children = [c for c in chunks if not c.is_parent]
    parents = [c for c in chunks if c.is_parent]
    # Nothing chunked yet, or pulled without artifacts. Writing an empty table
    # raises out of the driver with a message about schemas, which says nothing
    # about the actual problem: `rag chunk` has not been run.
    if not children:
        return 0, len(parents)

    db = lance.connect(paths.index)
    lance.write_table(db, lance.PARENTS, [lance.parent_row(c) for c in parents], True)

    encoder = encoder or load_encoder(config)
    first = True
    written = 0
    for batch in batched(children, 256):
        vectors = encode_texts(encoder, [c.embedding_text for c in batch], config)
        rows = [lance.child_row(c, v) for c, v in zip(batch, vectors, strict=True)]
        lance.write_table(db, lance.CHILDREN, rows, overwrite=first)
        first = False
        written += len(rows)
        if progress is not None:
            progress(written, len(children))

    lance.build_fts(db.open_table(lance.CHILDREN))
    return written, len(parents)


def search(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    paths: Paths,
    query: str,
    *,
    limit: int = 8,
    course: str = "",
    expand: bool = True,
    encoder: Encoder | None = None,
    config: EmbedConfig | None = None,
) -> list[Hit]:
    """Search the index and return passages ready to cite."""
    config = config or EmbedConfig()
    db = lance.connect(paths.index)
    if lance.CHILDREN not in db.table_names():
        return []

    encoder = encoder or load_encoder(config)
    vector = encode_texts(encoder, [query], config)[0]
    matches = lance.search_children(
        db.open_table(lance.CHILDREN), query, vector, limit=limit, course=course
    )
    if not expand or lance.PARENTS not in db.table_names():
        return [_hit(row, row["body"]) for row in matches]

    parents = lance.fetch_parents(
        db.open_table(lance.PARENTS), [row["parent_id"] for row in matches]
    )
    return _expanded(matches, parents)


def fetch(paths: Paths, chunk_id: str) -> Neighbourhood | None:
    """One chunk and its neighbours, for following an argument past its edges.

    Read from the chunk store rather than the index, because document order is
    exact there and a citation that has already been returned needs no search.
    A child resolves to its parent, on the same reasoning as search expansion:
    the child is what matched, the parent is what is worth reading.
    """
    slug = locate_chunk(paths, chunk_id)
    if not slug:
        return None

    chunks = list(read_chunks(paths, slug))
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    target = by_id.get(chunk_id)
    if target is None:
        return None

    matched = ""
    parent = by_id.get(target.parent_id)
    if not target.is_parent and parent is not None:
        matched, target = target.text, parent

    order = [chunk for chunk in chunks if chunk.is_parent == target.is_parent]
    at = order.index(target)
    return Neighbourhood(
        chunk=_from_chunk(target, matched),
        previous=_from_chunk(order[at - 1]) if at > 0 else None,
        following=_from_chunk(order[at + 1]) if at + 1 < len(order) else None,
    )


def _from_chunk(chunk: Chunk, matched: str = "") -> Hit:
    """A stored chunk, in the shape callers already know how to cite."""
    return Hit(
        chunk_id=chunk.chunk_id,
        book_slug=chunk.book_slug,
        breadcrumb=chunk.breadcrumb,
        text=chunk.text,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        courses=chunk.courses,
        score=0.0,
        matched_text=matched,
    )


def _expanded(
    matches: Sequence[dict[str, Any]], parents: dict[str, dict[str, Any]]
) -> list[Hit]:
    """Replace each match with its parent, keeping one hit per parent."""
    hits: list[Hit] = []
    seen: set[str] = set()
    for row in matches:
        parent = parents.get(str(row.get("parent_id", "")))
        if parent is None:
            hits.append(_hit(row, str(row["body"])))
            continue
        key = str(parent["chunk_id"])
        if key in seen:
            continue
        seen.add(key)
        hits.append(_hit(parent, str(parent["body"]), row))
    return hits


def _hit(row: dict[str, Any], body: str, matched: dict[str, Any] | None = None) -> Hit:
    courses = str(row.get("courses") or "")
    source = matched or row
    return Hit(
        chunk_id=str(row["chunk_id"]),
        book_slug=str(row["book_slug"]),
        breadcrumb=str(row["breadcrumb"]),
        text=body,
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
        courses=tuple(c for c in courses.split(",") if c),
        score=float(source.get("_relevance_score") or 0.0),
        matched_text=str(matched["body"]) if matched else "",
    )
