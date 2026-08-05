from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from imat_rag import cli, config
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


def test_serve_runs_the_mcp_server_over_the_resolved_knowledge_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(kb))
    served: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        cli,
        "run_server",
        lambda paths, transport: served.append((paths.kb_root, transport)),
    )

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0, result.output
    assert served == [(kb.resolve(), "stdio")]


def test_serve_accepts_another_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))
    served: list[str] = []
    monkeypatch.setattr(
        cli, "run_server", lambda paths, transport: served.append(transport)
    )

    result = runner.invoke(app, ["serve", "--transport", "streamable-http"])

    assert result.exit_code == 0, result.output
    assert served == ["streamable-http"]
