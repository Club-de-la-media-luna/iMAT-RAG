from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import pytest

from imat_rag.config import Paths
from imat_rag.publish import (
    DEFAULT_REPO,
    PUBLISHED,
    CannotReachHub,
    NothingToPublish,
    Pointer,
    RepositoryIsPublic,
    patterns,
    pull,
    push,
    read_pointer,
)


class FakeRepoInfo:
    def __init__(self, private: bool) -> None:
        self.private = private


class FakeCommit:
    def __init__(self, oid: str) -> None:
        self.oid = oid


class FakeHub:
    """The slice of huggingface_hub this package uses, recorded not performed."""

    def __init__(self, private: bool = True, exists: bool = True) -> None:
        self.private = private
        self.exists = exists
        self.created: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []
        self.downloads: list[dict[str, Any]] = []

    def create_repo(self, repo_id: str, **kwargs: Any) -> None:
        self.created.append({"repo_id": repo_id, **kwargs})
        self.exists = True

    def repo_info(self, repo_id: str, **_: Any) -> FakeRepoInfo:
        if not self.exists:
            raise FileNotFoundError(repo_id)
        return FakeRepoInfo(self.private)

    def upload_folder(self, **kwargs: Any) -> FakeCommit:
        self.uploads.append(kwargs)
        return FakeCommit("c0ffee1234")

    def snapshot_download(self, **kwargs: Any) -> str:
        self.downloads.append(kwargs)
        return str(kwargs.get("local_dir", ""))


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def with_artifacts(paths: Paths) -> Paths:
    """A knowledge base that has been through the whole pipeline."""
    for name in ("extracted", "figures", "chunks", "index"):
        (paths.derived / name).mkdir(parents=True, exist_ok=True)
        (paths.derived / name / "something").write_text("x")
    paths.manifest.write_text('{"books": []}')
    # Working directories the pipeline leaves behind, which are not artifacts.
    for name in ("bench", "blocks", "work"):
        (paths.derived / name).mkdir(parents=True, exist_ok=True)
        (paths.derived / name / "large").write_text("y" * 100)
    literature = paths.literature("DRL")
    literature.mkdir(parents=True, exist_ok=True)
    (literature / "a-book.pdf").write_text("%PDF-1.4")
    return paths


def patterns_of(hub: FakeHub) -> list[str]:
    return [str(p) for p in hub.uploads[0]["allow_patterns"]]


def test_pushing_creates_the_dataset_repository_private(tmp_path: Path) -> None:
    """The index can be inverted back towards its sources; see ADR-0001."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()

    push(paths, hub=hub)

    assert hub.created[0]["private"] is True
    assert hub.created[0]["repo_type"] == "dataset"


def test_pushing_defaults_to_the_group_dataset_repository(tmp_path: Path) -> None:
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()

    push(paths, hub=hub)

    assert hub.uploads[0]["repo_id"] == DEFAULT_REPO


def test_pushing_uploads_the_artifacts_and_nothing_else(tmp_path: Path) -> None:
    """`bench`, `blocks` and `work` are scratch, and would treble the payload."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()

    push(paths, hub=hub)

    patterns = patterns_of(hub)
    for name in PUBLISHED:
        assert any(f"derived/{name}" in pattern for pattern in patterns), name
    assert not any("bench" in p or "blocks" in p or "work" in p for p in patterns)


def test_the_repository_mirrors_the_knowledge_base_it_came_from(
    tmp_path: Path,
) -> None:
    """One rule: the Hub holds exactly what git cannot, at the paths git uses.

    Uploading from the root rather than from `derived/` is what makes a pulled
    revision drop back into place, and what lets one sha describe both the
    sources and the index built from them.
    """
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()

    push(paths, hub=hub)

    assert Path(hub.uploads[0]["folder_path"]) == paths.kb_root
    assert all(
        p.startswith("derived/") or p.startswith("courses/") for p in patterns_of(hub)
    )


def test_pushing_carries_the_source_pdfs_too(tmp_path: Path) -> None:
    """The books are the one thing a dead disk actually destroys."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()

    push(paths, hub=hub)

    assert any(p.endswith(".pdf") for p in patterns_of(hub))


def test_the_source_patterns_cover_every_kind_of_acquired_material() -> None:
    """A lecture deck is as unbacked as a book. Only the guides live in git."""
    globs = patterns(sources=True)

    def covered(path: str) -> bool:
        return any(fnmatch(path, glob) for glob in globs)

    assert covered("courses/IAP/raw/literature/bishop-2006.pdf")
    # Everything taken from a drop is filed by topic, a level deeper than a book.
    assert covered("courses/DRL/raw/slides/tema-2/representationlearning-1a.pdf")
    assert covered("courses/GI/raw/exams/tema-1/hoja1.pdf")
    assert covered("courses/MP/raw/notes/tema-1/inter-probabilistico.pdf")
    assert covered("courses/IM/raw/assignments/tema-4/12-unit-4-practica-docker.pdf")
    # A notebook is acquired material as much as a deck is, and so is the
    # Markdown some material arrived as, and an exercise project's own code.
    assert covered("courses/MGP/raw/code/t3-flow-models/ffjord.ipynb")
    assert covered("courses/IM/raw/exams/general/repaso-teoria.md")
    assert covered("courses/GI/raw/code/tema-4-ejercicio-monte/train.py")
    assert covered("courses/GI/raw/code/tema-4-ejercicio-monte/data/trees.csv")
    assert covered("courses/GI/raw/code/tema-4-ejercicio-monte/topo_model.pt")
    # Ours, small, and describes everything else; the Hub holds what git cannot.
    assert not covered("courses/MGP/raw/guide.pdf")
    # Sidecars and ledgers are text, and git keeps them.
    assert not covered("courses/MGP/raw/code/t3-flow-models/ffjord.txt")


def test_pushing_can_leave_the_sources_alone(tmp_path: Path) -> None:
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()

    push(paths, hub=hub, sources=False)

    assert not any(p.endswith(".pdf") for p in patterns_of(hub))


def test_pushing_refuses_a_public_repository(tmp_path: Path) -> None:
    """Shipping a vector store of copyrighted books is shipping the books."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub(private=False)

    with pytest.raises(RepositoryIsPublic):
        push(paths, hub=hub)

    assert hub.uploads == []


def test_pushing_nothing_is_an_error_not_an_empty_upload(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    hub = FakeHub()

    with pytest.raises(NothingToPublish):
        push(paths, hub=hub)

    assert hub.uploads == []


def test_pushing_records_the_revision_beside_the_knowledge_base(
    tmp_path: Path,
) -> None:
    """Git keeps the pointer, the Hub keeps the payload. The pointer binds them."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))

    pointer = push(paths, hub=FakeHub())

    assert pointer == Pointer(repo_id=DEFAULT_REPO, revision="c0ffee1234")
    assert read_pointer(paths) == pointer


def test_a_knowledge_base_that_has_never_been_pushed_has_no_pointer(
    tmp_path: Path,
) -> None:
    assert read_pointer(make_kb(tmp_path / "kb")) is None


def test_a_hub_refusal_explains_what_is_missing(tmp_path: Path) -> None:
    """A read-only token is the likely cause, and a traceback does not say so."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))

    class Refusing(FakeHub):
        def create_repo(self, repo_id: str, **kwargs: Any) -> None:
            raise RuntimeError("403 Forbidden")

    with pytest.raises(CannotReachHub) as raised:
        push(paths, hub=Refusing())

    assert "token" in str(raised.value)
    assert "403 Forbidden" in str(raised.value)


def test_a_hub_refusal_on_pull_explains_itself_too(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")

    class Refusing(FakeHub):
        def snapshot_download(self, **kwargs: Any) -> str:
            raise RuntimeError("401 Unauthorized")

    with pytest.raises(CannotReachHub):
        pull(paths, hub=Refusing())


def test_a_failed_pull_records_no_pointer(tmp_path: Path) -> None:
    """Recording a revision that was never downloaded would be a lie."""
    paths = make_kb(tmp_path / "kb")

    class Refusing(FakeHub):
        def snapshot_download(self, **kwargs: Any) -> str:
            raise RuntimeError("401 Unauthorized")

    with pytest.raises(CannotReachHub):
        pull(paths, hub=Refusing())

    assert read_pointer(paths) is None


def test_pulling_unpacks_into_the_knowledge_base_root(tmp_path: Path) -> None:
    """The repository mirrors the kb, so a revision drops straight back in."""
    paths = make_kb(tmp_path / "kb")
    hub = FakeHub()

    pull(paths, hub=hub, repo_id=DEFAULT_REPO, revision="abc123")

    assert Path(hub.downloads[0]["local_dir"]) == paths.kb_root
    assert hub.downloads[0]["repo_type"] == "dataset"
    assert hub.downloads[0]["revision"] == "abc123"


def test_pulling_leaves_the_source_pdfs_behind_by_default(tmp_path: Path) -> None:
    """Somebody who only wants to search should not fetch 1.1 GB of books."""
    paths = make_kb(tmp_path / "kb")
    hub = FakeHub()

    pull(paths, hub=hub)

    assert not any(str(p).endswith(".pdf") for p in hub.downloads[0]["allow_patterns"])


def test_pulling_can_ask_for_the_sources_as_well(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    hub = FakeHub()

    pull(paths, hub=hub, sources=True)

    assert any(str(p).endswith(".pdf") for p in hub.downloads[0]["allow_patterns"])


def test_pulling_follows_the_recorded_revision_by_default(tmp_path: Path) -> None:
    """Two people asking for "the index" must get the same one."""
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()
    push(paths, hub=hub)

    pull(paths, hub=hub)

    assert hub.downloads[0]["revision"] == "c0ffee1234"
    assert hub.downloads[0]["repo_id"] == DEFAULT_REPO


def test_an_explicit_revision_wins_over_the_recorded_one(tmp_path: Path) -> None:
    paths = with_artifacts(make_kb(tmp_path / "kb"))
    hub = FakeHub()
    push(paths, hub=hub)

    pull(paths, hub=hub, revision="older")

    assert hub.downloads[0]["revision"] == "older"


def test_pulling_without_a_pointer_takes_the_tip(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    hub = FakeHub()

    pointer = pull(paths, hub=hub)

    assert hub.downloads[0]["revision"] == "main"
    assert pointer.repo_id == DEFAULT_REPO


def test_pulling_records_what_was_pulled(tmp_path: Path) -> None:
    """A pulled knowledge base can say which revision it is holding."""
    paths = make_kb(tmp_path / "kb")

    pull(paths, hub=FakeHub(), revision="abc123")

    assert read_pointer(paths) == Pointer(repo_id=DEFAULT_REPO, revision="abc123")
