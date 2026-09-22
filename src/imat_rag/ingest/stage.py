"""Sorting a flat drop of downloads into the tree the pipeline reads.

Moodle hands over one PDF at a time, into whatever directory the browser was
pointed at. There is no structure to read there, so the name carries the whole
address: `<course>_<kind>_<topic>_<title>.pdf`.

Naming is the downloader's job, and this module's job is to refuse anything
that was named badly rather than to guess. A guessed `kind` is a guessed
`SourceTier`, and the tier is what decides whose answer wins when the corpus
disagrees with itself — a deck outranks a student's summary. Guessing that is
worse than leaving the file on the floor where it can be seen.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from imat_rag.config import Paths
from imat_rag.coverage import COURSE_NAMES
from imat_rag.ingest.catalogue import sha256_of
from imat_rag.ingest.staged import TIERS, intake_path, read_intake

SEPARATOR = "_"
"""What splits the fields of a name. Topics and titles use `-` for this
reason: `dgm-08-agent-eval` is one field, not three."""

FIELDS = 4
"""course, kind, topic, title. The title may itself contain separators, so
this is the number of splits, not the number of parts."""

DEFAULT_STAGING = Path("staging")
"""Where the sorted tree is built when no other place is given: beside the
corpus, so the review step is in the same repository as what it feeds."""

ARCHIVE = "moodle"
"""What the intake record calls a drop nothing else named. M9 filed one
colleague's archive; a semester's downloads come from the course pages."""

STAGING_ORIGIN = "staged"
"""Prefix for the origin of a file taken from a staging tree rather than from
a named archive. The origin must say where a file came from, and after the
inbox is emptied the staging path is the only honest answer left."""

CLASSIFIED = "named by the downloader"
"""Why this file has the kind it has. M9 classified by position in somebody
else's tree and had to guess; here the name is a declaration, and saying so
keeps the two intakes honest about how much each one knows."""

UNSAFE = re.compile(r"[`\r\n\x00-\x1f/\\]")
"""Characters that must not reach a path or a title. The name becomes a
directory name and a Markdown title downstream; a separator inside it writes
outside the tree, and a backtick closes a ledger entry early."""


class Named(BaseModel, frozen=True):
    """One download whose name says where it belongs."""

    course: str
    kind: str
    topic: str
    stem: str
    filename: str = ""


class Unreadable(BaseModel, frozen=True):
    """One download that could not be addressed, and why."""

    filename: str
    reason: str


def parse_filename(  # pylint: disable=too-many-return-statements
    filename: str,
) -> Named | Unreadable:
    """Read `<course>_<kind>_<topic>_<title>.pdf`, or say why it cannot be."""
    if UNSAFE.search(filename):
        return Unreadable(
            filename=filename, reason="the name contains characters a path cannot hold"
        )
    if not filename.lower().endswith(".pdf"):
        return Unreadable(filename=filename, reason="only PDFs are taken")

    parts = Path(filename).stem.split(SEPARATOR, FIELDS - 1)
    if len(parts) < FIELDS:
        return Unreadable(
            filename=filename,
            reason=(
                "expected <course>_<kind>_<topic>_<title>.pdf; "
                f"got {len(parts)} fields, so the kind is missing"
            ),
        )

    course, kind, topic, stem = parts
    if course.upper() not in COURSE_NAMES:
        return Unreadable(filename=filename, reason=f"{course} is not a course code")
    if kind.lower() not in TIERS:
        return Unreadable(
            filename=filename,
            reason=f"{kind} is not one of the kinds {', '.join(TIERS)}",
        )
    if not topic or not stem:
        return Unreadable(filename=filename, reason="the topic or the title is empty")

    return Named(
        course=course.upper(),
        kind=kind.lower(),
        topic=topic.lower(),
        stem=stem,
        filename=filename,
    )


class Sorted(BaseModel):
    """What one pass over the inbox filed, skipped and refused."""

    sorted: list[Named] = Field(default_factory=list)
    already: list[Named] = Field(default_factory=list)
    unreadable: list[Unreadable] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Every file that was looked at."""
        return len(self.sorted) + len(self.already) + len(self.unreadable)


def destination_of(named: Named) -> Path:
    """Where a named download sits, relative to the root of a corpus.

    The same shape the corpus already uses, so taking a staging tree in is a
    copy rather than a translation.
    """
    return (
        Path("courses")
        / named.course
        / "raw"
        / named.kind
        / named.topic
        / f"{named.stem}.pdf"
    )


def sort_into(inbox: Path, staging: Path) -> Sorted:
    """Copy every correctly named PDF in `inbox` into the staging tree.

    Copied, not moved: the inbox is the browser's download directory and
    emptying somebody's Downloads is not this tool's business. A file whose
    name cannot be read is left alone and reported, to be renamed and the
    whole pass re-run — which is why a destination that already exists is
    reported rather than overwritten.
    """
    filed: list[Named] = []
    already: list[Named] = []
    unreadable: list[Unreadable] = []

    for path in sorted(inbox.iterdir()):
        if not path.is_file():
            continue
        read = parse_filename(path.name)
        if isinstance(read, Unreadable):
            unreadable.append(read)
            continue

        target = staging / destination_of(read)
        if target.is_file():
            already.append(read)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        filed.append(read)

    return Sorted(sorted=filed, already=already, unreadable=unreadable)


class Taken(BaseModel):
    """What one pass over the staging tree filed, skipped and refused."""

    taken: list[Named] = Field(default_factory=list)
    duplicates: list[Named] = Field(default_factory=list)
    unreadable: list[Unreadable] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Every file that was looked at."""
        return len(self.taken) + len(self.duplicates) + len(self.unreadable)


def named_from(relative: Path) -> Named | Unreadable:
    """Read a staged path back into the fields its name carried.

    The inverse of :func:`destination_of`. The staging tree is written by this
    module, but it is a directory a person edits between the two steps, so it
    is read as strictly as the inbox was.
    """
    parts = relative.parts
    if len(parts) != 6 or parts[0] != "courses" or parts[2] != "raw":
        return Unreadable(
            filename=str(relative),
            reason="expected courses/<CODE>/raw/<kind>/<topic>/<file>.pdf",
        )
    _, course, _, kind, topic, filename = parts
    if course not in COURSE_NAMES:
        return Unreadable(filename=str(relative), reason=f"{course} is not a course")
    if kind not in TIERS:
        return Unreadable(filename=str(relative), reason=f"{kind} is not a known kind")
    return Named(
        course=course,
        kind=kind,
        topic=topic,
        stem=Path(filename).stem,
        filename=filename,
    )


def title_for(named: Named) -> str:
    """`MGP · Teoria · Dgm 08 Agent Eval` — what a citation shows.

    A slug is not a citation. The same shape M9 wrote, so the two intakes
    read alike.
    """
    return " · ".join(
        [named.course, _capitalised(named.topic), _capitalised(named.stem)]
    )


def _capitalised(slug: str) -> str:
    return " ".join(
        word.capitalize() for word in re.sub(r"[-_]+", " ", slug).strip().split()
    )


def _pages_with_pymupdf(path: Path) -> int:
    # pylint: disable=import-outside-toplevel
    import fitz

    with fitz.open(path) as doc:
        return len(doc)


def _held_already(paths: Paths) -> set[str]:
    """Hashes of every PDF the corpus already holds, under any course."""
    held: set[str] = set()
    for course in COURSE_NAMES:
        raw = paths.courses / course / "raw"
        if raw.is_dir():
            held.update(sha256_of(existing) for existing in raw.rglob("*.pdf"))
    return held


def take(  # pylint: disable=too-many-locals
    paths: Paths,
    staging: Path,
    *,
    pages_of: Callable[[Path], int] | None = None,
    origin: str = "",
) -> Taken:
    """File everything in the staging tree into the corpus, and record it.

    Two steps rather than one because the staging tree is the only moment a
    misnamed download is cheap to fix: once a file is in the corpus it has an
    intake entry, a slug, extracted Markdown and content-addressed chunk ids.

    Idempotent. Re-running after renaming one file must not take the rest a
    second time, so a file whose bytes the corpus already holds is reported as
    a duplicate and left alone.
    """
    counted = pages_of or _pages_with_pymupdf
    held = _held_already(paths)
    known = {str(entry.get("sha256", "")) for entry in read_intake(paths)}
    fresh: list[dict[str, object]] = []
    taken: list[Named] = []
    duplicates: list[Named] = []
    unreadable: list[Unreadable] = []

    for source in sorted(staging.rglob("*.pdf")):
        relative = source.relative_to(staging)
        read = named_from(relative)
        if isinstance(read, Unreadable):
            unreadable.append(read)
            continue

        digest = sha256_of(source)
        if digest in held or digest in known:
            duplicates.append(read)
            continue

        target = paths.kb_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        held.add(digest)

        fresh.append(
            entry_for(
                read,
                relative,
                pages=counted(target),
                digest=digest,
                origin=origin or f"{STAGING_ORIGIN}/{relative.as_posix()}",
            )
        )
        taken.append(read)

    record(paths, fresh)
    return Taken(taken=taken, duplicates=duplicates, unreadable=unreadable)


def entry_for(  # pylint: disable=too-many-arguments
    named: Named,
    relative: Path,
    *,
    pages: int,
    digest: str,
    origin: str,
    classified: str = CLASSIFIED,
) -> dict[str, object]:
    """One intake entry, in the shape `collect_staged` and M9 both read."""
    return {
        "path": relative.as_posix(),
        "title": title_for(named),
        "course": named.course,
        "kind": named.kind,
        "topic": named.topic,
        "pages": pages,
        "sha256": digest,
        "origin": origin,
        "classified": classified,
    }


def record(paths: Paths, entries: list[dict[str, object]]) -> int:
    """Append entries the intake does not already carry, and say how many.

    The one place the intake record is written. `rag take` and `rag inbox`
    both file material the ledgers say nothing about, and a second writer
    would be a second chance to write a shape `collect_staged` cannot read.

    Keyed on the hash, so re-running either command over the same material
    leaves one entry rather than two.
    """
    recorded = read_intake(paths)
    known = {str(entry.get("sha256", "")) for entry in recorded}
    added = [entry for entry in entries if str(entry.get("sha256", "")) not in known]
    if not added:
        return 0

    target = intake_path(paths)
    archive = ARCHIVE
    if target.is_file():
        try:
            archive = str(json.loads(target.read_text(encoding="utf-8"))["archive"])
        except (ValueError, OSError, KeyError):
            archive = ARCHIVE
    target.write_text(
        json.dumps(
            {"archive": archive, "files": [*recorded, *added]},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(added)


__all__ = [
    "DEFAULT_STAGING",
    "FIELDS",
    "Named",
    "Sorted",
    "Taken",
    "Unreadable",
    "destination_of",
    "entry_for",
    "named_from",
    "parse_filename",
    "record",
    "sort_into",
    "take",
    "title_for",
]
