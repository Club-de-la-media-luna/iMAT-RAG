"""What is in the corpus, according to the ledgers.

The ledgers (`courses/<CODE>/literature.md`) are the authority on which books
were acquired and which bibliography section they came from. This module turns
them into Book records, resolving the fact that one book can serve several
courses — Murphy is listed by both IAP and MGP and must be indexed once, not
twice.
"""

from __future__ import annotations

import hashlib
import re
from enum import IntEnum
from pathlib import Path

from pydantic import BaseModel, Field

from imat_rag.config import Paths

ENTRY = re.compile(r"^### (?P<title>.+?)\s*$")
SECTION = re.compile(r"^## (?P<name>.+?)\s*$")
STATUS = re.compile(r"^- (?P<lang>ES|EN): (?P<mark>✅|⬇|🔗|❌)\s*(?P<rest>.*)$")
BACKTICKED = re.compile(r"`([^`]+)`")

ACQUIRED = "✅"


class SourceTier(IntEnum):
    """How authoritative a source is about what is actually examined.

    Ordinal on purpose: higher wins when the corpus disagrees with itself. A
    textbook is right about the subject; a lecturer's deck is right about the
    course, which is the question being asked here.

    `NOTES` sits below the books deliberately. It holds material a student
    wrote — summaries, cheat sheets, a log of commands that worked — which is
    often the clearest thing in the corpus and the least reliable. Retrieval
    must never let it cite as confidently as the deck it was made from.

    The rungs above `SLIDES` are provisional: nothing ranks on this field yet,
    it is carried on every chunk so that ranking can be added without a
    re-ingest.
    """

    NOTES = 0
    EXTRA_BOOK = 1
    BASIC_BOOK = 2
    GUIDE = 3
    EXAM = 4
    SLIDES = 5
    ASSIGNMENT = 6
    CODE = 7


def _section_to_tier(heading: str) -> SourceTier | None:
    """Map a ledger's `## Bibliografía ...` heading to a source tier."""
    lowered = heading.lower()
    if "básica" in lowered or "basica" in lowered:
        return SourceTier.BASIC_BOOK
    if "complementaria" in lowered or "extra" in lowered:
        return SourceTier.EXTRA_BOOK
    return None


class LedgerEntry(BaseModel, frozen=True):
    """One acquired bibliography entry, as recorded by one course."""

    course: str
    tier: SourceTier
    title: str
    filename: str


def parse_ledger(text: str, course: str) -> list[LedgerEntry]:
    """Read one `literature.md`, keeping only acquired (✅) entries.

    Entries marked ⬇ (pending), 🔗 (link-only) or ❌ (not found) have no file on
    disk and are deliberately dropped — `coverage` reports them separately.
    """
    entries: list[LedgerEntry] = []
    tier: SourceTier | None = None
    title: str | None = None

    for line in text.splitlines():
        if match := SECTION.match(line):
            tier = _section_to_tier(match.group("name"))
            continue
        if match := ENTRY.match(line):
            title = match.group("title")
            continue
        match = STATUS.match(line)
        if (
            not match
            or match.group("mark") != ACQUIRED
            or title is None
            or tier is None
        ):
            continue
        path = BACKTICKED.search(match.group("rest"))
        if not path:
            continue
        entries.append(
            LedgerEntry(
                course=course,
                tier=tier,
                title=title,
                filename=Path(path.group(1)).name,
            )
        )
    return entries


class Book(BaseModel, frozen=True):
    """A source document, identified by its file and content.

    `courses` is a list because the same book serves several courses. The book
    is stored, extracted and embedded once regardless.
    """

    slug: str
    path: Path
    courses: tuple[str, ...]
    titles: tuple[str, ...]
    tier: SourceTier
    pages: int = 0
    sha256: str = ""
    extraction_tier: str = "unknown"
    warnings: tuple[str, ...] = Field(default=())

    @property
    def is_scan(self) -> bool:
        """Whether the source has no text layer and depends entirely on OCR."""
        return self.extraction_tier == "scan"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    """Hash a file's contents, streaming so a 144 MB PDF stays out of memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def collect(paths: Paths, tier: SourceTier = SourceTier.BASIC_BOOK) -> list[Book]:
    """Build the deduplicated book list for one source tier.

    A book listed by several courses yields one Book carrying every course. When
    courses disagree about the tier — basic for one, complementary for another —
    the higher tier wins, since being required reading anywhere makes it
    required reading.
    """
    by_filename: dict[str, list[LedgerEntry]] = {}
    for ledger in sorted(paths.courses.glob("*/literature.md")):
        course = ledger.parent.name
        for entry in parse_ledger(ledger.read_text(encoding="utf-8"), course):
            by_filename.setdefault(entry.filename, []).append(entry)

    books: list[Book] = []
    for filename, entries in sorted(by_filename.items()):
        best = max(entry.tier for entry in entries)
        if best != tier:
            continue
        found = [
            candidate
            for entry in entries
            if (candidate := paths.literature(entry.course) / filename).is_file()
        ]
        if not found:
            continue
        books.append(
            Book(
                slug=Path(filename).stem,
                path=found[0],
                courses=tuple(sorted({entry.course for entry in entries})),
                titles=tuple(sorted({entry.title for entry in entries})),
                tier=best,
            )
        )
    return books
