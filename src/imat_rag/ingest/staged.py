"""What is in the corpus that no ledger describes.

The ledgers (`courses/<CODE>/literature.md`) are the authority on books, and
say nothing about a lecture deck: a bibliography has no section for the slides
of the course it belongs to. `intake.json` is the authority on everything taken
from a drop, and this module turns it into the same `Book` records the ledger
path produces, so extraction and chunking need to know only one shape.

One difference matters. A book's filename is unique across the whole corpus —
publishers see to that — while `hoja1.pdf` exists under four different courses.
Slugs here are therefore built from the whole position of the file, not its
name, because two books sharing a slug would overwrite each other's extracted
Markdown and the loss would be silent.
"""

from __future__ import annotations

import json
from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.catalogue import Book, SourceTier

INTAKE_NAME = "intake.json"
"""Where the record of taken material lives, beside the corpus and in git."""

TIERS = {
    "slides": SourceTier.SLIDES,
    "exams": SourceTier.EXAM,
    "assignments": SourceTier.ASSIGNMENT,
    "notes": SourceTier.NOTES,
    "code": SourceTier.CODE,
}
"""Which rung each kind sits on. A kind absent here would be filed and then
silently never indexed, so `tier_of` refuses rather than guessing."""

EXTRACTABLE = ".pdf"
"""mineru takes PDFs. Markdown needs no extraction and a notebook needs its
own converter; both are handled elsewhere rather than fudged through here."""


class UnknownKind(KeyError):
    """Raised when material is filed under a kind nothing knows how to rank."""


def tier_of(kind: str) -> SourceTier:
    """The rung a kind sits on, or a refusal naming the kind."""
    if kind not in TIERS:
        raise UnknownKind(
            f"{kind!r} is not a known kind; expected one of {', '.join(TIERS)}"
        )
    return TIERS[kind]


def intake_path(paths: Paths) -> Path:
    """Where the intake record lives."""
    return paths.kb_root / INTAKE_NAME


def read_intake(paths: Paths) -> list[dict[str, object]]:
    """Every file recorded as taken, or nothing if none has been."""
    target = intake_path(paths)
    if not target.is_file():
        return []
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    found = loaded.get("files", [])
    return [entry for entry in found if isinstance(entry, dict)]


def slug_for(relative: str) -> str:
    """A corpus-wide unique name, built from where the file sits.

    `courses/GI/raw/exams/tema-1/hoja1.pdf` becomes `gi-exams-tema-1-hoja1`:
    course, kind, topic and stem, with `raw` dropped as it says nothing.
    """
    parts = Path(relative).parts
    course, kind, topic = parts[1], parts[3], parts[4]
    stem = Path(parts[-1]).stem
    return "-".join(part.lower() for part in (course, kind, topic, stem))


def collect_staged(
    paths: Paths, kinds: tuple[str, ...] = (), suffix: str = EXTRACTABLE
) -> list[Book]:
    """Build Book records for material the intake record describes.

    An entry whose file has gone is skipped rather than fatal: the record says
    what was taken, not what is still on this disk, and somebody who pulled
    without `--sources` legitimately has the record and none of the files.
    """
    books: list[Book] = []
    for entry in read_intake(paths):
        relative = str(entry.get("path", ""))
        kind = str(entry.get("kind", ""))
        if not relative or kind not in TIERS:
            continue
        if kinds and kind not in kinds:
            continue
        if not relative.endswith(suffix):
            continue

        path = paths.kb_root / relative
        if not path.is_file():
            continue

        title = str(entry.get("title", "")) or slug_for(relative)
        books.append(
            Book(
                slug=slug_for(relative),
                path=path,
                courses=(str(entry.get("course", "")),),
                titles=(title,),
                tier=TIERS[kind],
            )
        )
    return sorted(books, key=lambda book: book.slug)
