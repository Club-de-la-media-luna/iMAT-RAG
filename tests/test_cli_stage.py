from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from imat_rag import config
from imat_rag.cli import app

runner = CliRunner()


def make_kb(root: Path) -> Path:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return root


def test_stage_sorts_the_inbox_and_names_what_it_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal is only useful if it says which file and why."""
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "mgp_slides_teoria_dgm-08-agent-eval.pdf").write_bytes(b"%PDF-1.4 a")
    (inbox / "mgp_tema1_repaso.pdf").write_bytes(b"%PDF-1.4 b")

    result = runner.invoke(
        app, ["stage", str(inbox), "--into", str(tmp_path / "staged")]
    )

    assert result.exit_code == 0, result.output
    assert "mgp_tema1_repaso.pdf" in result.output
    staged = tmp_path / "staged/courses/MGP/raw/slides/teoria/dgm-08-agent-eval.pdf"
    assert staged.is_file()


def test_take_files_the_staging_tree_into_the_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second step is what makes material visible to the pipeline."""
    kb = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(kb))
    staged = tmp_path / "staged/courses/MP/raw/notes/tema-3/beta.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"%PDF-1.4 mp")

    result = runner.invoke(
        app, ["take", "--from", str(tmp_path / "staged"), "--pages", "8"]
    )

    assert result.exit_code == 0, result.output
    assert (kb / "courses/MP/raw/notes/tema-3/beta.pdf").is_file()
    recorded = json.loads((kb / "intake.json").read_text())["files"]
    assert [entry["course"] for entry in recorded] == ["MP"]


def test_take_refuses_to_run_when_nothing_is_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence after a no-op reads as success; M9's first extractions did that."""
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb")))

    result = runner.invoke(app, ["take", "--from", str(tmp_path / "nowhere")])

    assert result.exit_code != 0
    assert "nothing" in result.output.lower()
