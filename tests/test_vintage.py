from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from imat_rag import config
from imat_rag.cli import app
from imat_rag.config import Paths
from imat_rag.coverage import coverage
from imat_rag.ingest.extract import BookMeta
from imat_rag.ingest.stage import take
from imat_rag.ingest.staged import read_intake
from imat_rag.supersession import (
    ACCEPTED,
    REJECTED,
    REVIEW,
    Supersession,
    read_supersessions,
    write_supersessions,
)

runner = CliRunner()

OLD = "mgp-slides-t3-flujos"
NEW = "mgp-slides-tema-3-flujos"


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def staged_pdf(staging: Path, relative: str, body: bytes) -> None:
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)


# --- intake -----------------------------------------------------------------


def test_taking_a_deck_records_the_year_it_was_taught(tmp_path: Path) -> None:
    paths = make_kb(tmp_path / "kb")
    staging = tmp_path / "staged"
    staged_pdf(staging, "courses/MGP/raw/slides/tema-3/flujos.pdf", b"%PDF-1.4 new")

    take(paths, staging, pages_of=lambda _: 20, year="2026-27")

    assert read_intake(paths)[0]["year"] == "2026-27"


def test_take_on_the_command_line_takes_an_explicit_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = make_kb(tmp_path / "kb").kb_root
    monkeypatch.setenv(config.ENV_VAR, str(kb))
    staging = tmp_path / "staged"
    staged_pdf(staging, "courses/MP/raw/slides/tema-2/parte1.pdf", b"%PDF-1.4 mp")

    result = runner.invoke(
        app,
        ["take", "--from", str(staging), "--pages", "8", "--year", "2027-28"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads((kb / "intake.json").read_text())["files"][0]["year"] == (
        "2027-28"
    )


def test_take_refuses_a_year_that_is_not_an_academic_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`2026` would sort after every `2026-27` and silently win every ranking."""
    monkeypatch.setenv(config.ENV_VAR, str(make_kb(tmp_path / "kb").kb_root))
    staging = tmp_path / "staged"
    staged_pdf(staging, "courses/MP/raw/slides/tema-2/parte1.pdf", b"%PDF-1.4 mp")

    result = runner.invoke(
        app, ["take", "--from", str(staging), "--pages", "8", "--year", "2026"]
    )

    assert result.exit_code != 0
    assert "2026" in result.output


# --- coverage ---------------------------------------------------------------


def a_deck(paths: Paths, slug: str) -> None:
    fields: dict[str, Any] = {
        "slug": slug,
        "courses": ("MGP",),
        "titles": (slug,),
        "tier": 5,
        "extraction_tier": "prose",
        "pages": 20,
        "page_span": (1, 20),
        "source_sha256": "0" * 64,
        "source_path": f"/x/{slug}.pdf",
        "stage_key": "k",
        "tool": "mineru",
        "figures": 0,
        "chars": 100,
    }
    paths.extracted.mkdir(parents=True, exist_ok=True)
    (paths.extracted / f"{slug}.meta.json").write_text(
        BookMeta(**fields).model_dump_json(), encoding="utf-8"
    )


def seed_two_years(paths: Paths, decided: str = "auto") -> None:
    (paths.kb_root / "intake.json").write_text(
        json.dumps(
            {
                "archive": "moodle",
                "files": [
                    {"path": "courses/MGP/raw/slides/t3/flujos.pdf", "kind": "slides"},
                    {
                        "path": "courses/MGP/raw/slides/tema-3/flujos.pdf",
                        "kind": "slides",
                        "year": "2026-27",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    a_deck(paths, OLD)
    a_deck(paths, NEW)
    write_supersessions(
        paths,
        [
            Supersession(
                successor=NEW,
                predecessors=(OLD,),
                grade="changed",
                added=0.4,
                dropped=0.1,
                decided=decided,
            )
        ],
    )


def test_coverage_says_how_much_of_a_course_is_this_years_material(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path / "kb")
    seed_two_years(paths)

    mgp = next(entry for entry in coverage(paths) if entry.course == "MGP")

    assert mgp.by_year == {"2025-26": 1, "2026-27": 1}
    assert mgp.superseded == 1


def test_coverage_on_the_command_line_shows_the_years(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(paths.kb_root))
    seed_two_years(paths)

    result = runner.invoke(app, ["coverage"])

    assert result.exit_code == 0, result.output
    assert "2026-27: 1" in result.output
    assert "1 superseded" in result.output


# --- rag refresh ------------------------------------------------------------


def test_refresh_accept_confirms_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(paths.kb_root))
    seed_two_years(paths, decided=REVIEW)

    result = runner.invoke(app, ["refresh", NEW, "--accept"])

    assert result.exit_code == 0, result.output
    assert read_supersessions(paths)[0].decided == ACCEPTED


def test_refresh_reject_puts_the_old_deck_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(paths.kb_root))
    seed_two_years(paths, decided=REVIEW)

    result = runner.invoke(app, ["refresh", NEW, "--reject"])

    assert result.exit_code == 0, result.output
    assert read_supersessions(paths)[0].decided == REJECTED


def test_refresh_accept_of_an_unknown_deck_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(paths.kb_root))

    result = runner.invoke(app, ["refresh", "nothing", "--accept"])

    assert result.exit_code != 0
    assert "nothing" in result.output


def test_refresh_with_nothing_pending_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence after a no-op reads as success."""
    paths = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(paths.kb_root))

    result = runner.invoke(app, ["refresh", "--year", "2026-27"])

    assert result.exit_code == 0, result.output
    assert "nothing" in result.output.lower()


def test_refresh_of_a_deck_the_intake_never_took_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = make_kb(tmp_path / "kb")
    monkeypatch.setenv(config.ENV_VAR, str(paths.kb_root))

    result = runner.invoke(app, ["refresh", "nowhere"])

    assert result.exit_code != 0
    assert "nowhere" in result.output
