"""Command line entry point."""

from __future__ import annotations

import typer

from imat_rag import config

app = typer.Typer(
    help="Retrieval over the MIA master's reading list.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Group the subcommands.

    Typer collapses an application with exactly one command into a bare
    command taking no subcommand name. This callback keeps ``rag <command>``
    working while ``paths`` is the only one.
    """


@app.command()
def paths() -> None:
    """Show the resolved knowledge base and artifact locations."""
    try:
        resolved = config.resolve()
    except config.KnowledgeBaseNotFound as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

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


if __name__ == "__main__":
    app()
