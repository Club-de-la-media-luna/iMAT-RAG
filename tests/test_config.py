from __future__ import annotations

from pathlib import Path

import pytest

from imat_rag import config


def make_kb(root: Path) -> Path:
    """Create the minimum tree that counts as a knowledge base."""
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice de guías docentes\n")
    return root


def test_resolves_a_sibling_knowledge_base(tmp_path: Path) -> None:
    make_kb(tmp_path / "master_kb")
    repo = tmp_path / "iMAT-RAG"
    repo.mkdir()

    assert config.resolve(start=repo).kb_root == (tmp_path / "master_kb").resolve()


def test_resolves_from_a_nested_working_directory(tmp_path: Path) -> None:
    make_kb(tmp_path / "master_kb")
    nested = tmp_path / "iMAT-RAG" / "src" / "imat_rag"
    nested.mkdir(parents=True)

    assert config.resolve(start=nested).kb_root == (tmp_path / "master_kb").resolve()


def test_environment_variable_wins_over_the_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_kb(tmp_path / "master_kb")
    elsewhere = make_kb(tmp_path / "elsewhere")
    monkeypatch.setenv(config.ENV_VAR, str(elsewhere))

    assert config.resolve(start=tmp_path).kb_root == elsewhere.resolve()


def test_a_bad_environment_variable_never_falls_back_to_the_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit path that is wrong must fail, not silently pick another KB."""
    make_kb(tmp_path / "master_kb")
    monkeypatch.setenv(config.ENV_VAR, str(tmp_path / "typo"))

    with pytest.raises(config.KnowledgeBaseNotFound, match=config.ENV_VAR):
        config.resolve(start=tmp_path)


def test_a_directory_without_the_marker_is_not_a_knowledge_base(
    tmp_path: Path,
) -> None:
    (tmp_path / "master_kb").mkdir()

    with pytest.raises(config.KnowledgeBaseNotFound):
        config.resolve(start=tmp_path)


def test_the_error_lists_every_location_tried(tmp_path: Path) -> None:
    with pytest.raises(config.KnowledgeBaseNotFound) as caught:
        config.resolve(start=tmp_path)

    message = str(caught.value)
    assert config.ENV_VAR in message
    assert str(tmp_path / config.SIBLING_NAME) in message


def test_rejects_a_root_that_is_not_a_knowledge_base(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="is not a knowledge base"):
        config.Paths(kb_root=tmp_path)


def test_derived_paths_hang_off_the_root(tmp_path: Path) -> None:
    paths = config.Paths(kb_root=make_kb(tmp_path))

    assert paths.extracted == tmp_path / "derived" / "extracted"
    assert paths.index == tmp_path / "derived" / "index"
    assert paths.manifest == tmp_path / "derived" / "manifest.json"
    assert (
        paths.literature("DRL") == tmp_path / "courses" / "DRL" / "raw" / "literature"
    )
    assert paths.ledger("DRL") == tmp_path / "courses" / "DRL" / "literature.md"
