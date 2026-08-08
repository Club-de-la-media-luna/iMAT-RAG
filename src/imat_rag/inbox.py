"""Taking material from a contributor's own repository.

A contributor duplicates the inbox template into their own namespace, keeps it
private, drags PDFs into `<COURSE>/<kind>/`, and adds a maintainer as a
collaborator. Nothing enters this organisation until someone runs `rag inbox`,
which is the point: the ingest step is the trust boundary, because after it the
content is embedded into an index the whole group pulls.

The folder path is the entire contribution protocol. It carries the two things
that cannot be recovered from a PDF — which Course it serves, and how
authoritative it is — and nothing here guesses at either. A drop that does not
say is reported, not filed somewhere plausible.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from imat_rag.config import Paths
from imat_rag.coverage import COURSE_NAMES
from imat_rag.publish import REPO_TYPE, Hub, explained, hub_client

HEADINGS = {
    "basic": "Bibliografía básica",
    "extra": "Bibliografía complementaria",
}
"""Kinds that map onto a bibliography section, and so onto a ledger entry."""

STORED_KINDS = ("slides", "exams")
"""Kinds kept for later. Nothing reads these tiers yet, so no ledger entry is
written — claiming coverage the pipeline does not have is worse than a gap."""

KINDS = (*HEADINGS, *STORED_KINDS)

FORGEABLE = re.compile(r"[`\r\n\x00-\x1f]")
"""Characters that let a name escape the ledger entry it is written into.

An entry is `- EN: ✅ \\`name\\`` in Markdown. A newline closes it and starts
another; a backtick closes the path early. Either lets a contributor write a
bibliography entry of their choosing — and `catalogue.collect` reads that
ledger to decide what is extracted and indexed, so a forged entry is not
merely cosmetic. Names are refused rather than escaped: no legitimate
filename in this corpus contains them, and a rejected drop is reported.
"""

MINIMUM_PAGES = 20
"""Below this a PDF is front matter, not a book.

Two ledger entries are already wrong this way — truncated previews marked as
acquired. They are worse than an honest gap, because `rag coverage` then
reports material that cannot answer anything."""

SOURCES_NAME = "sources.json"
"""Where the accepted source repositories are recorded, beside the corpus."""


class SourceRepoIsPublic(RuntimeError):
    """Raised when the source repository would expose the corpus."""


class Drop(BaseModel, frozen=True):
    """One file a contributor left, and what its path says about it."""

    course: str
    kind: str
    filename: str
    title: str = ""

    @property
    def heading(self) -> str:
        """The bibliography section this belongs under, if any."""
        return HEADINGS.get(self.kind, "")


class Rejected(BaseModel, frozen=True):
    """One file that could not be filed, and why."""

    path: str
    reason: str


class Report(BaseModel):
    """What one ingest took, skipped and refused."""

    repo_id: str
    accepted: list[Drop] = Field(default_factory=list)
    stored: list[Drop] = Field(default_factory=list)
    duplicates: list[Drop] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Every file that was looked at."""
        return (
            len(self.accepted)
            + len(self.stored)
            + len(self.duplicates)
            + len(self.rejected)
        )


def parse_drop(path: str) -> Drop | Rejected:  # pylint: disable=too-many-return-statements
    """Read `<COURSE>/<kind>/<file>.pdf`, or say why it cannot be read.

    Deliberately strict. The tree comes from a repository this organisation
    does not control, so a path that climbs out of its own directory is
    refused rather than normalised — a `..` here would write anywhere on disk.
    """
    if ".." in Path(path).parts or Path(path).is_absolute():
        return Rejected(path=path, reason="path climbs out of the drop")

    parts = [part for part in Path(path).parts if part not in (".", "")]
    if len(parts) != 3:
        return Rejected(
            path=path, reason="expected <COURSE>/<kind>/<file>.pdf, got a bare file"
        )

    course, kind, filename = parts
    if course not in COURSE_NAMES:
        return Rejected(path=path, reason=f"{course} is not a course code")
    if kind not in KINDS:
        return Rejected(path=path, reason=f"{kind} is not one of {', '.join(KINDS)}")
    if not filename.lower().endswith(".pdf"):
        return Rejected(path=path, reason="only PDFs are taken")
    if FORGEABLE.search(filename):
        return Rejected(
            path=path, reason="the filename contains characters a ledger cannot hold"
        )

    return Drop(course=course, kind=kind, filename=filename)


def title_from(filename: str) -> str:
    """A legible title for a drop that came without a sidecar."""
    stem = re.sub(r"[-_]+", " ", Path(filename).stem).strip()
    return " ".join(word.capitalize() for word in stem.split())


def add_entry(ledger: str, heading: str, title: str, filename: str) -> str:
    """Append one acquired entry to a bibliography section.

    A missing section is created rather than dropped: filing the book and
    silently losing its entry is the failure this whole command exists to
    prevent.
    """
    # The title arrives from a sidecar the contributor wrote, so it is capable
    # of the same forgery as the filename and is flattened to one line.
    entry = f"### {FORGEABLE.sub(' ', title).strip()}\n- EN: ✅ `{filename}`\n"
    marker = f"## {heading}"
    # Anchored to a line start: `### Bibliografía básica y sus fuentes` contains
    # `## Bibliografía básica` as a substring, and splitting on that would cut
    # inside an entry title and file the book under a heading that is not one.
    found = re.search(rf"^{re.escape(marker)}\s*$", ledger, re.MULTILINE)
    if not found:
        separator = "" if ledger.endswith("\n\n") else "\n"
        return f"{ledger}{separator}\n{marker}\n\n{entry}"

    head, rest = ledger[: found.start()], ledger[found.end() :]
    following = rest.find("\n## ")
    if following == -1:
        return f"{head}{marker}{rest.rstrip()}\n\n{entry}"
    return f"{head}{marker}{rest[:following].rstrip()}\n\n{entry}{rest[following:]}"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _held_already(paths: Paths) -> set[str]:
    """Hashes of every PDF already in the corpus, for whatever course.

    All of `raw/`, not only `literature/`. Stored kinds live beside it, and
    missing them meant every re-run re-copied the same decks and reported them
    as newly taken.
    """
    held: set[str] = set()
    for course in COURSE_NAMES:
        raw = paths.courses / course / "raw"
        if not raw.is_dir():
            continue
        held.update(_digest(existing) for existing in raw.rglob("*.pdf"))
    return held


def _pages_with_pymupdf(path: Path) -> int:
    # pylint: disable=import-outside-toplevel
    import fitz

    with fitz.open(path) as doc:
        return len(doc)


def sources_path(paths: Paths) -> Path:
    """Where accepted source repositories are recorded."""
    return paths.kb_root / SOURCES_NAME


def read_sources(paths: Paths) -> list[str]:
    """Every source repository material has been taken from."""
    target = sources_path(paths)
    if not target.is_file():
        return []
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [str(item) for item in loaded.get("sources", [])]


def add_source(paths: Paths, repo_id: str) -> list[str]:
    """Record a source repository, keeping the list unique and ordered."""
    known = read_sources(paths)
    if repo_id not in known:
        known.append(repo_id)
        sources_path(paths).write_text(
            json.dumps({"sources": known}, indent=2) + "\n", encoding="utf-8"
        )
    return known


def _destination(paths: Paths, drop: Drop) -> Path:
    """Where a drop is filed. `basic` and `extra` share the literature tree."""
    if drop.kind in HEADINGS:
        return paths.literature(drop.course) / drop.filename
    return paths.courses / drop.course / "raw" / drop.kind / drop.filename


def _titled(staged: Path, drop: Drop) -> Drop:
    """A drop carrying its sidecar title, or one derived from the filename."""
    sidecar = staged.with_suffix(".txt")
    if sidecar.is_file():
        first = sidecar.read_text(encoding="utf-8").strip().splitlines()
        if first and first[0].strip():
            return drop.model_copy(update={"title": first[0].strip()})
    return drop.model_copy(update={"title": title_from(drop.filename)})


def ingest(
    paths: Paths,
    repo_id: str,
    *,
    hub: Hub | None = None,
    pages_of: Callable[[Path], int] | None = None,
) -> Report:
    """Take everything filed correctly in one contributor's repository.

    Material is copied, never referenced: once it is here the source repository
    can vanish — which it may, since it belongs to somebody else's account.
    """
    client = hub or hub_client()
    pages = pages_of or _pages_with_pymupdf

    with explained(repo_id):
        info = client.repo_info(repo_id, repo_type=REPO_TYPE)
    if not getattr(info, "private", False):
        raise SourceRepoIsPublic(
            f"{repo_id} is public. It holds course material that is not ours to "
            "publish; make it private before it is ingested."
        )

    report = Report(repo_id=repo_id)
    held = _held_already(paths)

    with tempfile.TemporaryDirectory() as staging:
        root = Path(staging)
        with explained(repo_id):
            client.snapshot_download(
                repo_id=repo_id,
                repo_type=REPO_TYPE,
                local_dir=str(root),
                allow_patterns=["*.pdf", "*.txt"],
            )
        _take(paths, root, report, held, pages)

    add_source(paths, repo_id)
    return report


def _take(
    paths: Paths,
    root: Path,
    report: Report,
    held: set[str],
    pages: Callable[[Path], int],
) -> None:
    """File every PDF found under a downloaded drop."""
    for staged in sorted(root.rglob("*")):
        if not staged.is_file() or staged.suffix.lower() != ".pdf":
            continue

        relative = staged.relative_to(root).as_posix()
        parsed = parse_drop(relative)
        if isinstance(parsed, Rejected):
            report.rejected.append(parsed)
            continue

        drop = _titled(staged, parsed)
        digest = _digest(staged)
        if digest in held:
            report.duplicates.append(drop)
            # Held, but perhaps by another course. Murphy is listed by IAP and
            # by MGP; skipping the copy is right, skipping the second course's
            # ledger entry loses that course a book it is meant to have.
            _record(paths, drop)
            continue

        # Always opened, so a corrupt file is caught here rather than hours
        # later in extraction — but one bad file must not abandon the drop.
        try:
            counted = pages(staged)
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
            report.rejected.append(
                Rejected(path=relative, reason=f"cannot be read: {exc}")
            )
            continue

        # The floor exists to catch truncated book previews marked as acquired.
        # A deck or an exam sheet is legitimately four pages, and applying the
        # floor to them rejected most of what a course actually sets.
        if drop.heading and counted < MINIMUM_PAGES:
            report.rejected.append(
                Rejected(
                    path=relative,
                    reason=f"{counted} pages — front matter, not a book",
                )
            )
            continue

        target = _destination(paths, drop)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, target)
        held.add(digest)

        if not drop.heading:
            report.stored.append(drop)
            continue

        _record(paths, drop)
        report.accepted.append(drop)


def _record(paths: Paths, drop: Drop) -> None:
    """Write one bibliography entry, unless the ledger already carries it.

    Idempotent because `rag inbox` is meant to be safe to re-run: a second pass
    over the same repository must not leave the ledger listing a book twice.
    """
    if not drop.heading:
        return
    ledger = paths.ledger(drop.course)
    existing = ledger.read_text(encoding="utf-8") if ledger.is_file() else ""
    if f"`{drop.filename}`" in existing:
        return
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        add_entry(existing, drop.heading, drop.title, drop.filename),
        encoding="utf-8",
    )


def ingest_all(
    paths: Paths, *, hub: Hub | None = None, pages_of: Any = None
) -> list[Report]:
    """Re-take every registered source, for when several people have added."""
    return [
        ingest(paths, repo_id, hub=hub, pages_of=pages_of)
        for repo_id in read_sources(paths)
    ]


__all__ = [
    "MINIMUM_PAGES",
    "Drop",
    "Rejected",
    "Report",
    "SourceRepoIsPublic",
    "add_entry",
    "add_source",
    "ingest",
    "ingest_all",
    "parse_drop",
    "read_sources",
    "title_from",
]
