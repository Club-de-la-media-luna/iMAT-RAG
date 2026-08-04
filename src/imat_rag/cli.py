"""Command line entry point."""

from __future__ import annotations

import typer

from imat_rag import config
from imat_rag.ingest.catalogue import SourceTier, collect
from imat_rag.ingest.extract import ExtractConfig, describe, extract_book

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


if __name__ == "__main__":
    app()
