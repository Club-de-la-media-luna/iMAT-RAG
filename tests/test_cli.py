from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from imat_rag import config
from imat_rag.cli import app

runner = CliRunner()


def make_kb(root: Path) -> Path:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice de guías docentes\n")
    return root


def test_paths_is_reachable_as_a_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typer collapses single-command apps; `rag paths` must still parse."""
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))

    result = runner.invoke(app, ["paths"])

    assert result.exit_code == 0, result.output


def test_paths_reports_every_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(kb))

    result = runner.invoke(app, ["paths"])

    for label in ("knowledge base", "courses", "extracted", "index", "manifest"):
        assert label in result.output
    assert str(kb.resolve()) in result.output


def test_paths_marks_locations_that_do_not_exist_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))

    result = runner.invoke(app, ["paths"])

    # `derived/` is not created until the first stage runs.
    assert "? extracted" in result.output
    assert "  courses" in result.output


def test_paths_fails_loudly_when_no_knowledge_base_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(tmp_path / "nope"))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["paths"])

    assert result.exit_code == 1
    assert config.ENV_VAR in result.output


def test_bare_invocation_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "paths" in result.output
