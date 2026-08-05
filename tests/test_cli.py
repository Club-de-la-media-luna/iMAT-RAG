from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from imat_rag import cli, config
from imat_rag.cli import app
from imat_rag.publish import CannotReachHub, NothingToPublish, Pointer

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


def test_pull_downloads_the_recorded_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(kb))
    monkeypatch.setattr(
        cli,
        "pull_artifacts",
        lambda paths, revision: Pointer(
            repo_id="org/data", revision=revision or "main"
        ),
    )

    result = runner.invoke(app, ["pull"])

    assert result.exit_code == 0, result.output
    assert "org/data" in result.output
    assert "main" in result.output


def test_pull_accepts_an_explicit_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))
    asked: list[str] = []
    monkeypatch.setattr(
        cli,
        "pull_artifacts",
        lambda paths, revision: (
            asked.append(revision) or Pointer(repo_id="org/data", revision=revision)
        ),
    )

    result = runner.invoke(app, ["pull", "--revision", "abc123"])

    assert result.exit_code == 0, result.output
    assert asked == ["abc123"]


def test_pull_explains_a_hub_refusal_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))

    def refuse(paths: object, revision: str) -> None:
        raise CannotReachHub("the Hub refused org/data: 401. Check your token.")

    monkeypatch.setattr(cli, "pull_artifacts", refuse)

    result = runner.invoke(app, ["pull"])

    assert result.exit_code == 1
    assert "token" in result.output


def test_push_reports_the_revision_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))
    monkeypatch.setattr(
        cli,
        "push_artifacts",
        lambda paths, message: Pointer(repo_id="org/data", revision="c0ffee"),
    )

    result = runner.invoke(app, ["push"])

    assert result.exit_code == 0, result.output
    assert "c0ffee" in result.output


def test_push_explains_itself_when_there_is_nothing_indexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))

    def refuse(paths: object, message: str) -> None:
        raise NothingToPublish("no manifest; run `rag chunk` and `rag index` first")

    monkeypatch.setattr(cli, "push_artifacts", refuse)

    result = runner.invoke(app, ["push"])

    assert result.exit_code == 1
    assert "rag index" in result.output


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
