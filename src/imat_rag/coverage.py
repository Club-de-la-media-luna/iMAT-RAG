"""What the corpus contains, per course — and what it does not.

Coverage is a first-class answer, not a report. A course with no acquired
books gets no material rather than material drawn from an adjacent subject,
and both the CLI and the MCP server need to say so in the same terms.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field, computed_field

from imat_rag.config import Paths
from imat_rag.ingest.catalogue import SourceTier
from imat_rag.ingest.store import extracted_books, read_manifest

COURSE_NAMES = {
    "DRL": "Deep Reinforcement Learning",
    "EE": "Ética y explicabilidad",
    "GI": "Geometría de la información",
    "IAG": "Inteligencia artificial geométrica",
    "IAP": "Inteligencia artificial probabilística",
    "IM": "Ingeniería de modelos",
    "MD": "Modelos diferenciales",
    "MGP": "Modelos generativos profundos",
    "MP": "Métodos probabilísticos",
}


def kind_of(tier: int) -> str:
    """A readable name for a source tier, for reporting rather than ranking."""
    try:
        return SourceTier(tier).name.lower().replace("_", " ")
    except ValueError:
        return "unknown"


class CourseCoverage(BaseModel, frozen=True):
    """What one course has indexed."""

    course: str
    name: str
    books: int = 0
    pages: int = 0
    chunks: int = 0
    book_slugs: tuple[str, ...] = ()
    by_kind: dict[str, int] = Field(default_factory=dict)
    """How the sources break down. "30 sources" is not an answer when fifteen
    of them are lab sheets and one is a student's cheat sheet."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def indexed(self) -> bool:
        """Whether the course has any material at all.

        Computed rather than plain so that a client reading the serialised
        form is told about the hole instead of having to infer it from zeroes.
        """
        return self.books > 0


def coverage(paths: Paths) -> list[CourseCoverage]:
    """Per-course totals for every course, including the empty ones.

    Every course appears whether or not it has material: a hole that is not
    reported is a hole the caller will answer around.
    """
    chunks_by_slug = {book.slug: book.chunks for book in read_manifest(paths).books}
    totals: dict[str, dict[str, int]] = {}
    slugs: dict[str, list[str]] = {}
    kinds: dict[str, Counter[str]] = {}

    for meta in extracted_books(paths):
        for course in meta.courses:
            entry = totals.setdefault(course, {"books": 0, "pages": 0, "chunks": 0})
            entry["books"] += 1
            entry["pages"] += meta.pages
            entry["chunks"] += chunks_by_slug.get(meta.slug, 0)
            slugs.setdefault(course, []).append(meta.slug)
            kinds.setdefault(course, Counter())[kind_of(meta.tier)] += 1

    return [
        CourseCoverage(
            course=course,
            name=name,
            book_slugs=tuple(sorted(slugs.get(course, ()))),
            by_kind=dict(kinds.get(course, Counter())),
            **totals.get(course, {}),
        )
        for course, name in sorted(COURSE_NAMES.items())
    ]
