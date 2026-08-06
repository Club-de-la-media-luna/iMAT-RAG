"""Command line entry point."""

from __future__ import annotations

import typer

from imat_rag import config
from imat_rag.coverage import COURSE_NAMES
from imat_rag.coverage import coverage as report_coverage
from imat_rag.inbox import SourceRepoIsPublic
from imat_rag.inbox import ingest as take_inbox
from imat_rag.inbox import ingest_all as take_all_inboxes
from imat_rag.index.search import build as build_index
from imat_rag.index.search import search as run_search
from imat_rag.ingest.catalogue import SourceTier, collect
from imat_rag.ingest.extract import ExtractConfig, describe, extract_book
from imat_rag.ingest.store import (
    ChunkConfig,
    Manifest,
    chunk_extracted_book,
    extracted_books,
    read_manifest,
    write_manifest,
)
from imat_rag.publish import CannotReachHub, NothingToPublish, RepositoryIsPublic
from imat_rag.publish import pull as pull_artifacts
from imat_rag.publish import push as push_artifacts
from imat_rag.serve import serve as run_server

app = typer.Typer(
    help="Retrieval over the MIA master's reading list.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Group the subcommands.

    Typer collapses an application with exactly one command into a bare
    command taking no subcommand name. This callback keeps ``rag <command>``
    working.
    """


def _resolve() -> config.Paths:
    try:
        return config.resolve()
    except config.KnowledgeBaseNotFound as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def paths() -> None:
    """Show the resolved knowledge base and artifact locations."""
    resolved = _resolve()
    rows = [
        ("knowledge base", resolved.kb_root),
        ("courses", resolved.courses),
        ("extracted", resolved.extracted),
        ("figures", resolved.figures),
        ("chunks", resolved.chunks),
        ("index", resolved.index),
        ("manifest", resolved.manifest),
    ]
    width = max(len(label) for label, _ in rows)
    for label, path in rows:
        mark = " " if path.exists() else "?"
        typer.echo(f"{mark} {label.ljust(width)}  {path}")


@app.command()
def courses() -> None:
    """List the courses in the knowledge base."""
    for code, name in COURSE_NAMES.items():
        typer.echo(f"{code:<4} --> {name}")


@app.command()
def books(
    tier: str = typer.Option("basic", help="basic or extra"),
    probe: bool = typer.Option(False, help="Open each PDF to report pages and tier"),
) -> None:
    """List the corpus as the ledgers describe it."""
    resolved = _resolve()
    wanted = SourceTier.BASIC_BOOK if tier == "basic" else SourceTier.EXTRA_BOOK
    found = collect(resolved, wanted)

    for book in found:
        detail = ""
        if probe:
            described = describe(book)
            flags = " ".join(described.warnings)
            detail = f"{described.pages:>5}p {described.extraction_tier:<12} {flags}"
        typer.echo(f"{','.join(book.courses):<10} {book.slug[:58]:<58} {detail}")

    typer.echo(f"\n{len(found)} books in the {tier} tier")


@app.command()
def extract(
    slug: str = typer.Option("", help="Extract only this book"),
    limit: int = typer.Option(0, help="Stop after this many books (0 = all)"),
    tier: str = typer.Option("basic", help="basic or extra"),
    timeout: int = typer.Option(14400, help="Per-book timeout in seconds"),
) -> None:
    """Convert books to Markdown. Safe to re-run: finished books are skipped."""
    resolved = _resolve()
    wanted = SourceTier.BASIC_BOOK if tier == "basic" else SourceTier.EXTRA_BOOK
    queue = [b for b in collect(resolved, wanted) if not slug or b.slug == slug]
    if limit:
        queue = queue[:limit]
    if not queue:
        typer.secho("nothing to extract", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)

    done = skipped = failed = 0
    for position, book in enumerate(queue, start=1):
        typer.echo(f"[{position}/{len(queue)}] {book.slug}")
        try:
            meta = extract_book(resolved, book, ExtractConfig(), timeout=timeout)
        # One bad book must not abandon an eleven-hour run; the failure is
        # reported and the queue continues.
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
            failed += 1
            typer.secho(f"    failed: {exc}", fg=typer.colors.RED, err=True)
            continue
        if meta is None:
            skipped += 1
            typer.echo("    already current")
            continue
        done += 1
        typer.echo(
            f"    {meta.pages}p {meta.extraction_tier} "
            f"{meta.chars} chars {meta.figures} figures "
            f"pages {meta.page_span[0]}-{meta.page_span[1]}"
        )

    typer.echo(f"\nextracted {done}, already current {skipped}, failed {failed}")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def chunk() -> None:
    """Chunk every extracted book and refresh the manifest."""
    resolved = _resolve()
    extracted = extracted_books(resolved)
    if not extracted:
        typer.secho("nothing extracted yet; run `rag extract`", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    entries = []
    for position, meta in enumerate(extracted, start=1):
        entry = chunk_extracted_book(resolved, meta)
        entries.append(entry)
        typer.echo(
            f"[{position}/{len(extracted)}] {entry.slug[:56]:<56} "
            f"{entry.chunks:>6} chunks ({entry.parents} parents)"
        )
    manifest = Manifest(chunk_config=ChunkConfig(), books=entries)
    write_manifest(resolved, manifest)
    typer.echo(f"\n{manifest.total_chunks} chunks across {len(manifest.books)} books")


@app.command()
def status() -> None:
    """Summarise what has been extracted and chunked so far."""
    resolved = _resolve()
    extracted = extracted_books(resolved)
    manifest = read_manifest(resolved)
    pages = sum(b.pages for b in extracted)
    scans = sum(1 for b in extracted if b.extraction_tier == "scan")

    typer.echo(f"extracted : {len(extracted)} books, {pages} pages, {scans} from scans")
    typer.echo(
        f"chunked   : {manifest.total_chunks} chunks across {len(manifest.books)} books"
    )
    for book in [b for b in extracted if b.warnings]:
        typer.echo(f"  ! {book.slug[:50]:<50} {'; '.join(book.warnings)}")


@app.command()
def coverage() -> None:
    """What the corpus does and does not contain, per course.

    The system is deliberately honest about its holes: a course with no
    acquired books gets no answer rather than one drawn from adjacent
    material.
    """
    for entry in report_coverage(_resolve()):
        if not entry.indexed:
            typer.secho(
                f"{entry.course:<4} {entry.name[:42]:<42} NO MATERIAL INDEXED",
                fg=typer.colors.YELLOW,
            )
            continue
        typer.echo(
            f"{entry.course:<4} {entry.name[:42]:<42} "
            f"{entry.books:>2} books {entry.pages:>6} pages "
            f"{entry.chunks:>6} chunks"
        )


@app.command()
def index() -> None:
    """Embed every child chunk and build the searchable index."""
    resolved = _resolve()

    def report(done: int, total: int) -> None:
        typer.echo(f"  embedded {done}/{total}", nl=False)
        typer.echo("\r", nl=False)

    typer.echo("loading BGE-M3 (first run downloads ~2.2 GB)...")
    children, parents = build_index(resolved, progress=report)
    typer.echo(f"\nindexed {children} children and {parents} parent sections")
    typer.echo(f"index at {resolved.index}")


@app.command()
def search(
    query: str = typer.Argument(..., help="What to look for"),
    limit: int = typer.Option(5, "--limit", "-k", help="How many passages"),
    course: str = typer.Option("", "--course", "-c", help="Scope to one course"),
    expand: bool = typer.Option(True, help="Return whole sections, not fragments"),
    full: bool = typer.Option(False, help="Print the whole passage"),
) -> None:
    """Search the corpus. Retrieval only — no model writes the answer."""
    resolved = _resolve()
    hits = run_search(resolved, query, limit=limit, course=course, expand=expand)
    if not hits:
        scope = f" for course {course}" if course else ""
        typer.secho(f"no material indexed{scope}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    for position, hit in enumerate(hits, start=1):
        typer.secho(f"\n[{position}] {hit.citation}", fg=typer.colors.CYAN)
        typer.echo(
            f"    {hit.book_slug} · {'/'.join(hit.courses)} · score {hit.score:.3f}"
        )
        body = hit.text if full else hit.text[:400].replace("\n", " ")
        typer.echo(f"    {body}{'' if full else ' ...'}")


@app.command()
def inbox(
    repo: str = typer.Argument("", help="A contributor's repository, or all known"),
) -> None:
    """Take material from a contributor's repository into the corpus.

    Files are copied, never referenced: the source belongs to somebody else's
    account and may vanish. Nothing is guessed — a drop whose path does not say
    which course and which tier it belongs to is reported, not filed.
    """
    resolved = _resolve()
    try:
        reports = [take_inbox(resolved, repo)] if repo else take_all_inboxes(resolved)
    except (SourceRepoIsPublic, CannotReachHub) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not reports:
        typer.secho(
            "no source repositories registered; pass one to add it",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    for report in reports:
        typer.secho(f"\n{report.repo_id}", fg=typer.colors.CYAN)
        for drop in report.accepted:
            typer.echo(f"  + {drop.course}/{drop.kind:<7} {drop.filename}")
        for drop in report.stored:
            typer.echo(
                f"  ~ {drop.course}/{drop.kind:<7} {drop.filename} (not indexed yet)"
            )
        for drop in report.duplicates:
            typer.echo(f"  = {drop.filename} already in the corpus")
        for refused in report.rejected:
            typer.secho(f"  ! {refused.path}: {refused.reason}", fg=typer.colors.YELLOW)
        typer.echo(
            f"  {len(report.accepted)} taken, {len(report.stored)} stored, "
            f"{len(report.duplicates)} already held, {len(report.rejected)} refused"
        )

    typer.echo("\nnow run `rag extract`, `rag chunk`, `rag index`, `rag push`")


@app.command()
def pull(
    revision: str = typer.Option(
        "", help="Pin an exact revision, or use the recorded one"
    ),
) -> None:
    """Download the corpus artifacts from the Hugging Face dataset repository."""
    typer.echo("downloading artifacts (~414 MB on a first pull)...")
    try:
        pointer = pull_artifacts(_resolve(), revision=revision)
    except CannotReachHub as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"pulled {pointer.repo_id} at {pointer.revision}")


@app.command()
def push(
    message: str = typer.Option("", "--message", "-m", help="Commit message"),
) -> None:
    """Publish the corpus artifacts, and record the revision for the group."""
    try:
        pointer = push_artifacts(_resolve(), message=message)
    except (NothingToPublish, RepositoryIsPublic, CannotReachHub) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"pushed {pointer.repo_id} at {pointer.revision}")
    typer.echo(
        f"commit the pointer in {config.SIBLING_NAME} so the group can follow it"
    )


@app.command()
def serve(
    transport: str = typer.Option("stdio", help="stdio, sse or streamable-http"),
) -> None:
    """Expose search, fetch and coverage to an agent over MCP."""
    run_server(_resolve(), transport)


if __name__ == "__main__":
    app()
