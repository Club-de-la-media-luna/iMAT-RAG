"""The searchable index: LanceDB, one directory, two tables.

Children carry the vectors and the full-text index because they are what a
query is matched against. Parents carry no vector at all — they are never
matched, only fetched once a child has won, so embedding them would be wasted
work and wasted disk.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from imat_rag.ingest.chunk import Chunk

CHILDREN = "children"
PARENTS = "parents"

TEXT_FIELD = "text"
VECTOR_FIELD = "vector"


def child_row(chunk: Chunk, vector: Sequence[float]) -> dict[str, Any]:
    """One searchable row.

    `text` is the embedded form — breadcrumb first — so the full-text index
    matches the same string the vector was built from. A query naming a chapter
    should find its sections lexically as well as semantically.
    """
    return {
        "chunk_id": chunk.chunk_id,
        "parent_id": chunk.parent_id,
        "book_slug": chunk.book_slug,
        "breadcrumb": chunk.breadcrumb,
        TEXT_FIELD: chunk.embedding_text,
        "body": chunk.text,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "courses": ",".join(chunk.courses),
        "source_tier": chunk.source_tier,
        "tokens": chunk.tokens,
        VECTOR_FIELD: list(vector),
    }


def parent_row(chunk: Chunk) -> dict[str, Any]:
    """One retrievable section, stored without a vector."""
    return {
        "chunk_id": chunk.chunk_id,
        "book_slug": chunk.book_slug,
        "breadcrumb": chunk.breadcrumb,
        "body": chunk.text,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "courses": ",".join(chunk.courses),
        "source_tier": chunk.source_tier,
        "tokens": chunk.tokens,
    }


def connect(index_dir: Path) -> Any:
    """Open the index directory, creating it if this is the first run."""
    # Lazy: lancedb pulls pyarrow, which is slow to import and irrelevant to
    # every command that does not touch the index.
    import lancedb  # pylint: disable=import-outside-toplevel

    index_dir.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(index_dir))


def write_table(
    db: Any, name: str, rows: Sequence[dict[str, Any]], overwrite: bool
) -> Any:
    """Create or append to a table, returning it."""
    if overwrite and name in db.table_names():
        db.drop_table(name)
    if name in db.table_names():
        table = db.open_table(name)
        if rows:
            table.add(list(rows))
        return table
    return db.create_table(name, data=list(rows))


def build_fts(table: Any) -> None:
    """Build the BM25 index that supplies the lexical half of hybrid search."""
    table.create_fts_index(TEXT_FIELD, replace=True)


def course_filter(course: str) -> str:
    """SQL predicate scoping a search to one course.

    Stored as a comma-joined string rather than a list, because a book belongs
    to several courses and LanceDB filters strings far more simply than arrays.
    """
    return f"courses LIKE '%{course}%'"


def search_children(
    table: Any,
    query: str,
    vector: Sequence[float],
    limit: int = 10,
    course: str = "",
) -> list[dict[str, Any]]:
    """Hybrid search: dense vector and BM25, fused by reciprocal rank."""
    request = table.search(query_type="hybrid").vector(list(vector)).text(query)
    if course:
        request = request.where(course_filter(course))
    return list(request.limit(limit).to_list())


def fetch_parents(table: Any, parent_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Load the sections behind a set of matched children."""
    wanted = [pid for pid in dict.fromkeys(parent_ids) if pid]
    if not wanted:
        return {}
    quoted = ", ".join(f"'{pid}'" for pid in wanted)
    rows = table.search().where(f"chunk_id IN ({quoted})").limit(len(wanted)).to_list()
    return {row["chunk_id"]: row for row in rows}
