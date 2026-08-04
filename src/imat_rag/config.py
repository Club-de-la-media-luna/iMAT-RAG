"""Locating the knowledge base and the artifacts derived from it.

This repository holds no data. Everything the pipeline reads and writes lives
in the ``master_kb`` repository, which is found at runtime rather than
configured at install time, so that the same wheel works for a contributor who
keeps it somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, field_validator

ENV_VAR = "MASTER_KB_PATH"
"""Environment variable holding an explicit path to the knowledge base."""

SIBLING_NAME = "master_kb"
"""Directory name looked for beside this repository when the env var is unset."""

MARKER = Path("courses") / "INDEX.md"
"""Relative path that must exist for a directory to be a knowledge base."""


class KnowledgeBaseNotFound(RuntimeError):
    """Raised when no directory satisfying :data:`MARKER` can be located."""


class Paths(BaseModel, frozen=True):
    """Resolved locations inside the knowledge base.

    Source material is read from ``courses``; everything the pipeline produces
    is written under ``derived``, which is gitignored in ``master_kb`` and
    shipped via the Hugging Face dataset repository instead.
    """

    kb_root: Path

    @field_validator("kb_root")
    @classmethod
    def _must_be_a_knowledge_base(cls, value: Path) -> Path:
        if not (value / MARKER).is_file():
            raise ValueError(f"{value} is not a knowledge base: {MARKER} is missing")
        return value

    @property
    def courses(self) -> Path:
        """Per-course source material, one directory per course code."""
        return self.kb_root / "courses"

    @property
    def derived(self) -> Path:
        """Root of everything the pipeline generates."""
        return self.kb_root / "derived"

    @property
    def extracted(self) -> Path:
        """Converted Markdown and its metadata sidecars, one pair per book."""
        return self.derived / "extracted"

    @property
    def figures(self) -> Path:
        """Images pulled out of the sources, namespaced by book slug."""
        return self.derived / "figures"

    @property
    def chunks(self) -> Path:
        """Chunked records awaiting embedding."""
        return self.derived / "chunks"

    @property
    def index(self) -> Path:
        """The LanceDB directory."""
        return self.derived / "index"

    @property
    def manifest(self) -> Path:
        """Record of which inputs and configuration produced the current index."""
        return self.derived / "manifest.json"

    def literature(self, course: str) -> Path:
        """Source PDFs for one course."""
        return self.courses / course / "raw" / "literature"

    def ledger(self, course: str) -> Path:
        """The acquisition ledger for one course."""
        return self.courses / course / "literature.md"


def candidate_roots(start: Path | None = None) -> list[Path]:
    """Directories named ``master_kb`` at or above ``start``, nearest first.

    ``start`` defaults to the current working directory, which is what makes
    the lookup work from anywhere inside either repository. This is the search
    used only when :data:`ENV_VAR` is unset.
    """
    here = (start or Path.cwd()).resolve()
    return [directory / SIBLING_NAME for directory in (here, *here.parents)]


def resolve(start: Path | None = None) -> Paths:
    """Find the knowledge base, or explain every place that was tried.

    :data:`ENV_VAR` is authoritative when set: a value pointing somewhere that
    is not a knowledge base is an error, not a reason to go looking elsewhere.
    Falling back would silently index a different corpus than the one asked
    for, which is far harder to notice than a failure.
    """
    from_env = os.environ.get(ENV_VAR)
    if from_env:
        explicit = Path(from_env).expanduser()
        if not (explicit / MARKER).is_file():
            raise KnowledgeBaseNotFound(
                f"{ENV_VAR}={from_env} is not a knowledge base: "
                f"{explicit / MARKER} is missing."
            )
        return Paths(kb_root=explicit.resolve())

    tried = candidate_roots(start)
    for candidate in tried:
        if (candidate / MARKER).is_file():
            return Paths(kb_root=candidate.resolve())

    listing = "\n  ".join(str(path) for path in tried)
    raise KnowledgeBaseNotFound(
        f"No knowledge base found. Set {ENV_VAR} to its path.\nTried:\n  {listing}"
    )
