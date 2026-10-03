"""Which of this year's decks replace which of last year's.

A record beside the corpus, not a field in the index. Ranking reads it at query
time, so accepting or rejecting a supersession re-embeds nothing and rewrites
no chunk — chunk ids stay content-addressed (ADR-0003) and the decision stays
reversible by editing one line of JSON. See ADR-0009.

This module only holds the record and answers "what supersedes this source?".
Measuring whether a deck *should* supersede another is `imat_rag.refresh`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from imat_rag.config import Paths
from imat_rag.ingest.staged import read_intake, slug_for, year_of

SUPERSESSIONS_NAME = "supersessions.json"
"""Beside `intake.json`, in git: small, and the answer to why ranking changed."""

TAU = 0.85
"""Cosine similarity at which two children say the same thing.

Measured on the published index (ADR-0009): versions of one deck cover each
other at ≥ 0.6 at this threshold, while different decks cover each other not
at all.
"""

DEMOTION = 0.6
"""What a predecessor's fused score is multiplied by. Enough to put a
successor's version of a passage first; not so much that material only the
predecessor holds drops out of the results."""

AUTO = "auto"
"""Decided by the grade alone: `same`, `revised`, or `new`."""

REVIEW = "review"
"""`changed`: it supersedes, but a human or agent should read the diagnosis."""

ACCEPTED = "accepted"
"""Confirmed after review."""

REJECTED = "rejected"
"""Turned down. Kept rather than deleted so that the next bulk refresh does not
propose the same supersession again; it ranks as though it were absent."""


class Measured(BaseModel, frozen=True):
    """What the grade was measured with, so it can be measured again."""

    tau: float
    model: str
    successor_children: int
    predecessor_children: int


class Supersession(BaseModel, frozen=True):
    """One successor deck and the sources it replaces."""

    successor: str
    predecessors: tuple[str, ...] = ()
    grade: str
    added: float = 0.0
    dropped: float = 0.0
    measured: Measured | None = None
    """Absent when the text alone settled it: identical text needs no vectors."""

    decided: str = AUTO

    @property
    def in_force(self) -> bool:
        """Whether ranking should act on this record."""
        return bool(self.predecessors) and self.decided != REJECTED


class Supersessions(BaseModel):
    """The whole record, as it sits on disk."""

    supersessions: list[Supersession] = Field(default_factory=list)


def supersessions_path(paths: Paths) -> Path:
    """Where the record lives."""
    return paths.kb_root / SUPERSESSIONS_NAME


def read_supersessions(paths: Paths) -> list[Supersession]:
    """Every recorded supersession, or none.

    An unreadable record reads as none rather than failing a search: the
    old decks then rank as they did before, which is wrong in a way nobody is
    harmed by.
    """
    target = supersessions_path(paths)
    if not target.is_file():
        return []
    try:
        loaded = Supersessions.model_validate_json(target.read_text(encoding="utf-8"))
    except (ValidationError, ValueError, OSError):
        return []
    return loaded.supersessions


def write_supersessions(paths: Paths, records: Iterable[Supersession]) -> None:
    """Replace the record. Sorted, so that a diff shows what was decided."""
    ordered = sorted(records, key=lambda record: record.successor)
    supersessions_path(paths).write_text(
        Supersessions(supersessions=ordered).model_dump_json(indent=1) + "\n",
        encoding="utf-8",
    )


def put(paths: Paths, record: Supersession) -> None:
    """Record a verdict, replacing any earlier one about the same successor."""
    kept = [r for r in read_supersessions(paths) if r.successor != record.successor]
    write_supersessions(paths, [*kept, record])


def fingerprint(paths: Paths) -> str:
    """SHA-256 of the record as it stands, or `""` if there is none."""
    target = supersessions_path(paths)
    if not target.is_file():
        return ""
    return hashlib.sha256(target.read_bytes()).hexdigest()


class Lineage(BaseModel, frozen=True):
    """What ranking needs to know about every source, read once per query."""

    # Plain defaults rather than `Field(default_factory=...)`: pydantic copies
    # them per instance, and pylint cannot see through `FieldInfo` to the
    # dict methods used below.
    successor_of: dict[str, tuple[str, ...]] = {}
    vintage: dict[str, str] = {}

    def successors_of(self, slug: str) -> tuple[str, ...]:
        """The decks superseding `slug`, empty if it is current."""
        return self.successor_of.get(slug, ())

    def vintage_of(self, slug: str) -> str:
        """The course year a source was taught in, `""` for a ledger book.

        A book is not taught in a year; it is published, and an edition is a
        different question from this one.
        """
        return self.vintage.get(slug, "")


def vintages(paths: Paths) -> dict[str, str]:
    """The course year of every source the intake took."""
    found: dict[str, str] = {}
    for entry in read_intake(paths):
        relative = str(entry.get("path", ""))
        if relative:
            found[slug_for(relative)] = year_of(entry)
    return found


def lineage(paths: Paths) -> Lineage:
    """Successors and vintages, as the record and the intake state them now."""
    successor_of: dict[str, list[str]] = {}
    for record in read_supersessions(paths):
        if not record.in_force:
            continue
        for predecessor in record.predecessors:
            successor_of.setdefault(predecessor, []).append(record.successor)
    return Lineage(
        successor_of={
            slug: tuple(sorted(found)) for slug, found in successor_of.items()
        },
        vintage=vintages(paths),
    )
