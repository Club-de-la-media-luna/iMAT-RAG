"""Shipping the corpus to the Hugging Face dataset repository, and back.

One rule decides what goes: **the repository holds exactly what git cannot**,
at the paths git uses. `master_kb` gitignores the acquired PDFs and `derived/`
— one book alone exceeds GitHub's file limit — so those two things are what
have no other home. Everything else there is small text that git already
carries.

Mirroring the knowledge base rather than uploading `derived/` on its own is
what lets one revision be a complete statement: these sources, and the index
built from them. A revision naming a bare index says nothing about what
produced it. See [ADR-0001](../../docs/adr/0001-public-code-private-data.md).

The repository is private and is checked to be private before anything is
uploaded. That is not caution about size: embeddings can be inverted towards
approximations of their source text, so a vector store built from copyrighted
textbooks is a weaker form of the textbooks themselves.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel

from imat_rag.config import Paths

DEFAULT_REPO = "Club-de-la-media-luna/master_kb"
"""The group's dataset repository. Private, under the same organisation as the code."""

REPO_TYPE = "dataset"

PUBLISHED = ("extracted", "figures", "chunks", "index", "manifest.json")
"""What is worth shipping out of `derived/`.

Everything the pipeline declares as an artifact, and nothing else: `bench`,
`blocks` and `work` are scratch left behind by extraction and would more than
double the payload without making a single query answerable.
"""

SOURCES = "courses/*/raw/literature/*.pdf"
"""The acquired PDFs — the one part of the corpus a dead disk destroys."""

POINTER_NAME = "corpus.json"
"""Where the revision is recorded, beside the corpus and tracked by git.

Named for what it pins rather than for one part of it: since the repository
carries the acquired books as well as the artifacts built from them, a
revision describes the whole corpus.
"""


class NothingToPublish(RuntimeError):
    """Raised when `derived/` holds no manifest, so no index exists to ship."""


class RepositoryIsPublic(RuntimeError):
    """Raised when the target repository would expose the corpus."""


class CannotReachHub(RuntimeError):
    """Raised when the Hub refuses the request, with what usually causes it."""


class Pointer(BaseModel, frozen=True):
    """Which revision of which repository this knowledge base is holding."""

    repo_id: str
    revision: str


class Hub(Protocol):
    """The slice of `huggingface_hub` this package depends on.

    A protocol so that publishing can be tested without a network, a token or
    a 414 MB upload.
    """

    def create_repo(self, repo_id: str, **kwargs: Any) -> Any:
        """Create the repository, or do nothing if it already exists."""

    def repo_info(self, repo_id: str, **kwargs: Any) -> Any:
        """Describe an existing repository."""

    def upload_folder(self, **kwargs: Any) -> Any:
        """Upload a directory as one commit."""

    def snapshot_download(self, **kwargs: Any) -> Any:
        """Download a revision of a repository into a local directory."""


def hub_client() -> Hub:
    """The real Hub client, imported late so that `rag paths` stays instant."""
    # pylint: disable=import-outside-toplevel
    from huggingface_hub import HfApi

    # `HfApi` spells each argument out where the protocol takes `**kwargs`, so
    # it satisfies the protocol in practice without matching it structurally.
    return cast(Hub, HfApi())


def pointer_path(paths: Paths) -> Path:
    """Where the revision pointer lives."""
    return paths.kb_root / POINTER_NAME


def read_pointer(paths: Paths) -> Pointer | None:
    """The revision this knowledge base last pushed or pulled, if any."""
    target = pointer_path(paths)
    if not target.is_file():
        return None
    try:
        return Pointer.model_validate_json(target.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def write_pointer(paths: Paths, pointer: Pointer) -> None:
    """Record a revision beside the knowledge base, for git to carry."""
    pointer_path(paths).write_text(
        pointer.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


@contextmanager
def explained(repo_id: str) -> Iterator[None]:
    """Turn a Hub refusal into the two things that actually cause it.

    A 401 or 403 here is almost never a bug: it is a read-only token, or an
    organisation the account is not a member of. The traceback says neither.
    """
    try:
        yield
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise CannotReachHub(
            f"the Hub refused {repo_id}: {exc}\n"
            "Check that the organisation exists, that you are a member of it, "
            "and that your token has write access — `huggingface-cli login` "
            "with a token from https://huggingface.co/settings/tokens."
        ) from exc


def patterns(sources: bool = False) -> list[str]:
    """Filters covering the artifacts, and optionally the books behind them.

    Paths are relative to the knowledge base root rather than to `derived/`,
    because the repository mirrors the knowledge base: a pulled revision drops
    straight back into place, and one revision describes both the sources and
    the index built from them.
    """
    wanted = [
        f"derived/{name}" if "." in name else f"derived/{name}/**" for name in PUBLISHED
    ]
    return [*wanted, SOURCES] if sources else wanted


def push(
    paths: Paths,
    *,
    repo_id: str = DEFAULT_REPO,
    hub: Hub | None = None,
    message: str = "",
    sources: bool = True,
) -> Pointer:
    """Upload the artifacts as one revision, and record which one.

    Returns the pointer that was written. Re-running is cheap: the Hub skips
    files whose hashes already match, so a rebuilt index uploads only what
    actually changed.
    """
    if not paths.manifest.is_file():
        raise NothingToPublish(
            f"no manifest at {paths.manifest}; run `rag chunk` and `rag index` first"
        )

    client = hub or hub_client()
    with explained(repo_id):
        client.create_repo(repo_id, repo_type=REPO_TYPE, private=True, exist_ok=True)
        info = client.repo_info(repo_id, repo_type=REPO_TYPE)

    if not getattr(info, "private", False):
        raise RepositoryIsPublic(
            f"{repo_id} is public. The index is as private as the PDFs it was "
            "built from; make the repository private before publishing."
        )

    with explained(repo_id):
        commit = client.upload_folder(
            repo_id=repo_id,
            repo_type=REPO_TYPE,
            folder_path=str(paths.kb_root),
            allow_patterns=patterns(sources),
            commit_message=message or "Publish the corpus",
        )

    pointer = Pointer(repo_id=repo_id, revision=str(getattr(commit, "oid", "main")))
    write_pointer(paths, pointer)
    return pointer


def pull(
    paths: Paths,
    *,
    repo_id: str = "",
    revision: str = "",
    hub: Hub | None = None,
    sources: bool = False,
) -> Pointer:
    """Download a revision into the knowledge base, and record what was taken.

    With no revision, the recorded one is used: two people asking for "the
    corpus" get the same corpus rather than whatever the tip happens to be.

    The source PDFs are left behind unless asked for. Somebody who only wants
    to search needs the index, not 1.1 GB of books they will never open.
    """
    recorded = read_pointer(paths)
    wanted = Pointer(
        repo_id=repo_id or (recorded.repo_id if recorded else DEFAULT_REPO),
        revision=revision or (recorded.revision if recorded else "main"),
    )

    client = hub or hub_client()
    paths.derived.mkdir(parents=True, exist_ok=True)
    with explained(wanted.repo_id):
        client.snapshot_download(
            repo_id=wanted.repo_id,
            repo_type=REPO_TYPE,
            revision=wanted.revision,
            local_dir=str(paths.kb_root),
            allow_patterns=patterns(sources),
        )

    write_pointer(paths, wanted)
    return wanted
