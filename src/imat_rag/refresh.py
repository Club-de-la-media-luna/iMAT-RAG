"""Measure whether this year's deck replaces last year's, and record the verdict.

Cheapest stage first, and a stage that settles the question stops the rest
(ADR-0009). Identical bytes never get this far — the intake refuses them.
Identical text is graded without a vector. Otherwise the new deck's children
are compared with last year's decks of the same course on the vectors the
index already holds, and graded by how much each side covers the other.

Nothing here judges whether the new deck is *better*. It measures how it
differs, and when the difference is large it writes a short report for an
agent to judge from — a few hundred tokens instead of two decks (ADR-0002:
the pipeline measures, the agent judges).
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel

from imat_rag.config import Paths
from imat_rag.index import lance
from imat_rag.index.embed import EmbedConfig, Encoder, load_encoder
from imat_rag.index.search import append, embed_children
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.staged import read_intake, slug_for, year_of
from imat_rag.ingest.store import (
    chunk_extracted_book,
    extracted_books,
    read_chunks,
    read_manifest,
    write_manifest,
)
from imat_rag.supersession import (
    ACCEPTED,
    AUTO,
    REJECTED,
    REVIEW,
    TAU,
    Measured,
    Supersession,
    put,
    read_supersessions,
)

SAME = "same"
REVISED = "revised"
CHANGED = "changed"
NEW = "new"

SAME_LIMIT = 0.05
"""Most a deck may add or drop and still be the same deck: a typo, a date."""

REVISED_LIMIT = 0.30
"""Most a deck may add or drop and supersede without a diagnosis.

Like every threshold here, set from five measured pairs and to be revisited
once ten real chapters have been through (ADR-0009)."""

PREDECESSOR_COVERAGE = 0.30
"""Share of the new deck an old one must cover to be its predecessor.

Versions of one deck measured ≥ 0.6; different decks, even in the same folder,
measured 0.00. Low enough that half of a deck split in two still finds it."""

TOLERANCE = 1e-9
"""So that `1 - 0.95` grades as the 0.05 it means rather than 0.0500…04."""

REFRESHED_KINDS = ("slides",)
"""What a bulk refresh looks at. An exam is not a version of last year's exam,
however many problems it reuses, and must not supersede it."""

EXCERPT = 200
"""Characters of each unmatched child the report quotes."""

ATOMIC_KINDS = (
    ("$$", "equations"),
    ("\\[", "equations"),
    ("|", "tables"),
    ("<table", "tables"),
    ("```", "code"),
    ("![", "figures"),
)
"""How a block announces what it is. `content_types` only says atomic or prose,
and "added 6 slides with equations" is the sentence worth reading."""

Best = tuple[float, int]
"""A child's closest match on the other side: similarity, and its position."""


class NotInIntake(LookupError):
    """Raised for a slug the intake record never took."""


class NotReady(RuntimeError):
    """Raised for a deck that has not been extracted yet."""


# --- measuring ----------------------------------------------------------------


def best_matches(
    rows: Sequence[Sequence[float]], against: Sequence[Sequence[float]]
) -> list[Best]:
    """For every row, its most similar row of `against` (cosine)."""
    if not against:
        return [(0.0, -1) for _ in rows]
    if not rows:
        return []
    # Lazy: numpy arrives with the index extra, and only refreshing needs it.
    import numpy  # pylint: disable=import-outside-toplevel

    left = numpy.asarray(rows, dtype=float)
    right = numpy.asarray(against, dtype=float)
    left /= numpy.maximum(numpy.linalg.norm(left, axis=1, keepdims=True), 1e-12)
    right /= numpy.maximum(numpy.linalg.norm(right, axis=1, keepdims=True), 1e-12)
    similarity = left @ right.T
    closest = similarity.argmax(axis=1)
    return [(float(similarity[i, j]), int(j)) for i, j in enumerate(closest.tolist())]


def covered(best: Sequence[Best], tau: float = TAU) -> float:
    """Share of children whose best match reaches `tau`."""
    if not best:
        return 0.0
    return sum(1 for similarity, _ in best if similarity >= tau) / len(best)


def grade(added: float, dropped: float, *, has_predecessor: bool) -> str:
    """The verdict the shares earn. Boundaries are inclusive."""
    if not has_predecessor:
        return NEW
    worst = max(added, dropped)
    if worst <= SAME_LIMIT + TOLERANCE:
        return SAME
    if worst <= REVISED_LIMIT + TOLERANCE:
        return REVISED
    return CHANGED


class Comparison(BaseModel, frozen=True):
    """How a new deck relates to the old decks it was measured against."""

    predecessors: tuple[str, ...] = ()
    added: float = 1.0
    """Share of the new deck nothing old covers."""

    dropped: float = 0.0
    """Share of the predecessors the new deck no longer covers."""

    grade: str = NEW
    successor_best: tuple[Best, ...] = ()
    predecessor_best: tuple[Best, ...] = ()


def classify(new_covered: float, old_covered: float) -> Comparison:
    """Grade from the two coverages alone, as the calibration table states them."""
    has_predecessor = new_covered >= PREDECESSOR_COVERAGE
    added = 1 - new_covered if has_predecessor else 1.0
    dropped = 1 - old_covered if has_predecessor else 0.0
    return Comparison(
        added=added,
        dropped=dropped,
        grade=grade(added, dropped, has_predecessor=has_predecessor),
    )


def find_predecessors(
    successor: Sequence[Sequence[float]],
    candidates: Mapping[str, Sequence[Sequence[float]]],
    topics: Mapping[str, str] | None = None,
    topic: str = "",
) -> list[str]:
    """Every old deck covering enough of the new one, best first.

    Many-to-many on purpose: a deck split in two is a predecessor of both
    halves, and two merged decks are both predecessors of the merge. The topic
    folder only breaks ties — it was `t3-flow-models` last year and `tema-3`
    this year, and a name that changes cannot be what decides.
    """
    named = topics or {}
    scored = [
        (slug, share)
        for slug, vectors in candidates.items()
        if (share := covered(best_matches(successor, vectors))) >= PREDECESSOR_COVERAGE
    ]
    scored.sort(
        key=lambda found: (
            -found[1],
            not topic or named.get(found[0]) != topic,
            found[0],
        )
    )
    return [slug for slug, _ in scored]


def compare(
    successor: Sequence[Sequence[float]],
    candidates: Mapping[str, Sequence[Sequence[float]]],
    topics: Mapping[str, str] | None = None,
    topic: str = "",
) -> Comparison:
    """Find a new deck's predecessors and grade it against all of them at once."""
    predecessors = find_predecessors(successor, candidates, topics, topic)
    if not predecessors:
        return Comparison(successor_best=tuple(best_matches(successor, [])))

    pooled = [vector for slug in predecessors for vector in candidates[slug]]
    forward = best_matches(successor, pooled)
    backward = best_matches(pooled, successor)
    added, dropped = 1 - covered(forward), 1 - covered(backward)
    return Comparison(
        predecessors=tuple(predecessors),
        added=added,
        dropped=dropped,
        grade=grade(added, dropped, has_predecessor=True),
        successor_best=tuple(forward),
        predecessor_best=tuple(backward),
    )


def _signature(chunks: Sequence[Chunk]) -> tuple[str, ...]:
    """Hashes of every child's text, folded for case and whitespace."""
    folded = (
        " ".join(chunk.text.casefold().split())
        for chunk in chunks
        if not chunk.is_parent
    )
    return tuple(sorted(hashlib.sha256(text.encode()).hexdigest() for text in folded))


def same_text(
    successor: Sequence[Chunk], candidates: Mapping[str, Sequence[Chunk]]
) -> str:
    """The old deck whose text the new one repeats exactly, or `""`."""
    wanted = _signature(successor)
    if not wanted:
        return ""
    for slug in sorted(candidates):
        if _signature(candidates[slug]) == wanted:
            return slug
    return ""


# --- order ------------------------------------------------------------------


def _matched(best: Sequence[Best], tau: float) -> list[tuple[int, int]]:
    """(new position, old position) for every child that found its match."""
    return [(i, j) for i, (similarity, j) in enumerate(best) if similarity >= tau]


def _in_order(values: Sequence[int]) -> set[int]:
    """Positions of a longest non-decreasing run through `values`."""
    tails: list[int] = []
    tail_at: list[int] = []
    back = [-1] * len(values)
    for k, value in enumerate(values):
        slot = bisect_right(tails, value)
        if slot:
            back[k] = tail_at[slot - 1]
        if slot == len(tails):
            tails.append(value)
            tail_at.append(k)
        else:
            tails[slot], tail_at[slot] = value, k
    keep: set[int] = set()
    k = tail_at[-1] if tail_at else -1
    while k >= 0:
        keep.add(k)
        k = back[k]
    return keep


def out_of_order(best: Sequence[Best], tau: float = TAU) -> list[int]:
    """New positions of matched children that were moved, not rewritten.

    The fewest children whose removal leaves the rest in last year's order.
    Reported, never graded: coverage cannot see order, so a reshuffle already
    adds nothing to `added` or `dropped`.
    """
    matched = _matched(best, tau)
    keep = _in_order([j for _, j in matched])
    return [i for k, (i, _) in enumerate(matched) if k not in keep]


def rank_correlation(best: Sequence[Best], tau: float = TAU) -> float:
    """Kendall's rank correlation between new and old positions of matches."""
    old = [j for _, j in _matched(best, tau)]
    concordant = discordant = 0
    for a, first in enumerate(old):
        for second in old[a + 1 :]:
            if second > first:
                concordant += 1
            elif second < first:
                discordant += 1
    pairs = len(old) * (len(old) - 1) // 2
    return (concordant - discordant) / pairs if pairs else 1.0


# --- diagnosis --------------------------------------------------------------


def kinds_in(chunks: Sequence[Chunk]) -> list[str]:
    """What sort of material a group of children is: equations, tables, …"""
    found: set[str] = set()
    for chunk in chunks:
        for block in re.split(r"\n{2,}", chunk.text):
            found.update(
                kind
                for prefix, kind in ATOMIC_KINDS
                if block.strip().startswith(prefix)
            )
    return sorted(found) or ["prose"]


def _pages(chunks: Sequence[Chunk]) -> str:
    start = min(chunk.page_start for chunk in chunks)
    end = max(chunk.page_end for chunk in chunks)
    return f"p. {start}" if start == end else f"pp. {start}-{end}"


def _grouped(chunks: Sequence[Chunk]) -> list[str]:
    """One line per section, with an excerpt of each child under it."""
    groups: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        groups.setdefault(chunk.breadcrumb, []).append(chunk)
    if not groups:
        return ["- nothing"]
    lines: list[str] = []
    for breadcrumb, members in groups.items():
        count = f"{len(members)} child{'ren' if len(members) != 1 else ''}"
        kinds = ", ".join(kinds_in(members))
        lines.append(f"- {breadcrumb}, {_pages(members)} · {count} · {kinds}")
        lines.extend(
            f"  > {' '.join(member.text.split())[:EXCERPT]}" for member in members
        )
    return lines


def _unmatched(
    chunks: Sequence[Chunk], best: Sequence[Best], tau: float
) -> list[Chunk]:
    return [
        chunk for chunk, (score, _) in zip(chunks, best, strict=False) if score < tau
    ]


def diagnose(
    successor: str,
    successor_children: Sequence[Chunk],
    predecessor_children: Sequence[Chunk],
    comparison: Comparison,
    tau: float = TAU,
) -> str:
    """The report an agent reads to judge a changed deck, in Markdown."""
    moved = [
        successor_children[i] for i in out_of_order(comparison.successor_best, tau)
    ]
    matched = len(_matched(comparison.successor_best, tau))
    correlation = rank_correlation(comparison.successor_best, tau)
    moved_lines = [
        (
            f"- {len(moved)} of {matched} matched children moved; "
            f"Kendall rank correlation {correlation:.2f}"
        ),
        *(f"  > {child.breadcrumb}, p. {child.page_start}" for child in moved),
    ]
    replaces = ", ".join(comparison.predecessors) or "nothing"
    summary = (
        f"Grade **{comparison.grade}** · added {comparison.added:.2f} · "
        f"dropped {comparison.dropped:.2f} · τ {tau} · supersedes {replaces}"
    )
    return "\n".join(
        [
            f"# Refresh: {successor}",
            "",
            summary,
            "",
            "## Added",
            "",
            *_grouped(_unmatched(successor_children, comparison.successor_best, tau)),
            "",
            "## Dropped",
            "",
            *_grouped(
                _unmatched(predecessor_children, comparison.predecessor_best, tau)
            ),
            "",
            "## Moved",
            "",
            *moved_lines,
            "",
        ]
    )


# --- the corpus ---------------------------------------------------------------


class Source(BaseModel, frozen=True):
    """One file the intake took, as far as refreshing cares."""

    slug: str
    course: str
    kind: str
    topic: str
    year: str


def sources(paths: Paths) -> list[Source]:
    """Everything the intake record took."""
    return [
        Source(
            slug=slug_for(str(entry["path"])),
            course=str(entry.get("course", "")),
            kind=str(entry.get("kind", "")),
            topic=str(entry.get("topic", "")),
            year=year_of(entry),
        )
        for entry in read_intake(paths)
        if entry.get("path")
    ]


def _source(paths: Paths, slug: str) -> Source:
    for source in sources(paths):
        if source.slug == slug:
            return source
    raise NotInIntake(f"{slug} is not in the intake record; `rag take` files decks")


def _older(paths: Paths, target: Source) -> list[Source]:
    """Earlier decks of the same course and kind: the only possible predecessors."""
    return [
        source
        for source in sources(paths)
        if source.course == target.course
        and source.kind == target.kind
        and source.year < target.year
        and source.slug != target.slug
    ]


def _children(paths: Paths, slug: str) -> list[Chunk]:
    return [chunk for chunk in read_chunks(paths, slug) if not chunk.is_parent]


def chunks_of(paths: Paths, target: Source) -> list[Chunk]:
    """The new deck's chunks, chunking it now if `rag chunk` has not."""
    manifest = read_manifest(paths)
    chunked = list(read_chunks(paths, target.slug))
    if chunked and any(book.slug == target.slug for book in manifest.books):
        return chunked

    meta = next((m for m in extracted_books(paths) if m.slug == target.slug), None)
    if meta is None:
        raise NotReady(
            f"{target.slug} has not been extracted; run "
            f"`rag extract --tier {target.kind} --slug {target.slug}` first"
        )
    entry = chunk_extracted_book(paths, meta)
    manifest.books = [b for b in manifest.books if b.slug != target.slug] + [entry]
    write_manifest(paths, manifest)
    return list(read_chunks(paths, target.slug))


def pending(paths: Paths, year: str) -> list[str]:
    """This year's decks that have no verdict yet."""
    decided = {record.successor for record in read_supersessions(paths)}
    return sorted(
        source.slug
        for source in sources(paths)
        if source.year == year
        and source.kind in REFRESHED_KINDS
        and source.slug not in decided
    )


def _decide(paths: Paths, slug: str, decided: str) -> bool:
    for record in read_supersessions(paths):
        if record.successor == slug:
            put(paths, record.model_copy(update={"decided": decided}))
            _restamp(paths)
            return True
    return False


def accept(paths: Paths, slug: str) -> bool:
    """Confirm a verdict after review. False if there is none to confirm."""
    return _decide(paths, slug, ACCEPTED)


def reject(paths: Paths, slug: str) -> bool:
    """Turn a supersession down; the old deck ranks first again, nothing rebuilt."""
    return _decide(paths, slug, REJECTED)


def _restamp(paths: Paths) -> None:
    """Fingerprint the record in the manifest, if there is a manifest to stamp."""
    if paths.manifest.is_file():
        write_manifest(paths, read_manifest(paths))


# --- the pipeline -------------------------------------------------------------


class Refreshed(BaseModel):
    """What one refresh decided, wrote and indexed."""

    record: Supersession
    report: Path | None = None
    indexed: int = 0
    """Children appended to the index; 0 when the deck was already there."""


class _Vectors:
    """Vectors from the index where it has them, from the encoder where not.

    The encoder is loaded only when something is missing. On the common path
    — last year's decks published, this year's not yet indexed — that is once,
    for the new deck alone.
    """

    def __init__(self, paths: Paths, load: Callable[[], Encoder], config: EmbedConfig):
        db = lance.connect(paths.index)
        self.table = (
            db.open_table(lance.CHILDREN)
            if lance.CHILDREN in db.table_names()
            else None
        )
        self.load = load
        self.config = config
        self.encoder: Encoder | None = None
        self.embedded: dict[str, dict[str, list[float]]] = {}

    def indexed(self, slug: str) -> dict[str, list[float]]:
        """What the index already holds for one source."""
        return lance.vectors_of(self.table, slug) if self.table is not None else {}

    def of(self, chunks: Sequence[Chunk]) -> dict[str, list[float]]:
        """Every child's vector, embedding only what the index lacks."""
        if not chunks:
            return {}
        slug = chunks[0].book_slug
        children = [c for c in chunks if not c.is_parent]
        if slug not in self.embedded:
            held = self.indexed(slug)
            if not all(c.chunk_id in held for c in children):
                if self.encoder is None:
                    self.encoder = self.load()
                held = embed_children(children, self.encoder, self.config)
            self.embedded[slug] = held
        return self.embedded[slug]


def _measure(
    target: Source,
    children: list[Chunk],
    older: Mapping[str, list[Chunk]],
    vectors: _Vectors,
    topics: Mapping[str, str],
) -> tuple[Comparison, list[Chunk]]:
    """Compare on vectors; return the comparison and the pooled old children."""
    mine = vectors.of(children)
    theirs = {slug: vectors.of(chunks) for slug, chunks in older.items()}
    comparison = compare(
        [mine[c.chunk_id] for c in children],
        {slug: [theirs[slug][c.chunk_id] for c in older[slug]] for slug in older},
        topics=topics,
        topic=target.topic,
    )
    pooled = [c for slug in comparison.predecessors for c in older[slug]]
    return comparison, pooled


def _report_path(paths: Paths, slug: str) -> Path:
    return paths.derived / "refresh" / f"{slug}.md"


def refresh(  # pylint: disable=too-many-arguments
    paths: Paths,
    slug: str,
    *,
    encoder: Encoder | None = None,
    load: Callable[[], Encoder] | None = None,
    config: EmbedConfig | None = None,
    report: bool = False,
) -> Refreshed:
    """Grade one deck against last year's, record the verdict, and index it.

    `report` writes the diagnosis for a `revised` deck too; a `changed` one
    always gets it.
    """
    settings = config or EmbedConfig()
    loader = (lambda: encoder) if encoder is not None else load
    vectors = _Vectors(paths, loader or (lambda: load_encoder(settings)), settings)

    target = _source(paths, slug)
    chunks = chunks_of(paths, target)
    record, written = _graded(paths, target, chunks, vectors, report)

    put(paths, record)
    _restamp(paths)
    indexed = 0
    if not vectors.indexed(slug):
        indexed, _ = append(paths, chunks, vectors.of(chunks))
    return Refreshed(record=record, report=written, indexed=indexed)


def _graded(
    paths: Paths,
    target: Source,
    chunks: Sequence[Chunk],
    vectors: _Vectors,
    report: bool,
) -> tuple[Supersession, Path | None]:
    """The verdict, and the report if one was written. Text first, then vectors."""
    children = [c for c in chunks if not c.is_parent]
    candidates = _older(paths, target)
    older = {s.slug: kids for s in candidates if (kids := _children(paths, s.slug))}
    if same := same_text(children, older):
        return (
            Supersession(successor=target.slug, predecessors=(same,), grade=SAME),
            None,
        )

    comparison, pooled = _measure(
        target, children, older, vectors, {s.slug: s.topic for s in candidates}
    )
    record = _recorded(
        target.slug, comparison, vectors.config, len(children), len(pooled)
    )
    if comparison.grade != CHANGED and not (report and comparison.predecessors):
        return record, None
    written = _report_path(paths, target.slug)
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(
        diagnose(target.slug, children, pooled, comparison), encoding="utf-8"
    )
    return record, written


def _recorded(
    slug: str,
    comparison: Comparison,
    config: EmbedConfig,
    successor_children: int,
    predecessor_children: int,
) -> Supersession:
    return Supersession(
        successor=slug,
        predecessors=comparison.predecessors,
        grade=comparison.grade,
        added=round(comparison.added, 4),
        dropped=round(comparison.dropped, 4),
        measured=Measured(
            tau=TAU,
            model=config.model,
            successor_children=successor_children,
            predecessor_children=predecessor_children,
        ),
        decided=REVIEW if comparison.grade == CHANGED else AUTO,
    )
