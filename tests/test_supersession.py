from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.staged import DEFAULT_YEAR, academic_year, year_of
from imat_rag.ingest.store import Manifest, read_manifest, write_manifest
from imat_rag.supersession import (
    ACCEPTED,
    AUTO,
    REJECTED,
    Measured,
    Supersession,
    fingerprint,
    lineage,
    put,
    read_supersessions,
    supersessions_path,
    write_supersessions,
)


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def write_intake(paths: Paths, files: list[dict[str, object]]) -> None:
    (paths.kb_root / "intake.json").write_text(
        json.dumps({"archive": "moodle", "files": files}), encoding="utf-8"
    )


def a_record(successor: str, *predecessors: str, decided: str = AUTO) -> Supersession:
    return Supersession(
        successor=successor,
        predecessors=predecessors,
        grade="revised" if predecessors else "new",
        added=0.12,
        dropped=0.03,
        measured=Measured(
            tau=0.85,
            model="BAAI/bge-m3",
            successor_children=41,
            predecessor_children=38,
        ),
        decided=decided,
    )


# --- vintage ----------------------------------------------------------------


def test_an_academic_year_turns_over_in_september() -> None:
    """The course year, not the calendar year: October 2026 is 2026-27."""
    assert academic_year(date(2026, 10, 3)) == "2026-27"
    assert academic_year(date(2027, 2, 1)) == "2026-27"
    assert academic_year(date(2026, 8, 31)) == "2025-26"


def test_an_entry_without_a_year_is_last_years_drop() -> None:
    """M9 wrote no year; everything it filed is the 2025-26 material."""
    assert DEFAULT_YEAR == "2025-26"
    assert year_of({"path": "x.pdf"}) == "2025-26"
    assert year_of({"path": "x.pdf", "year": "2026-27"}) == "2026-27"


# --- the record -------------------------------------------------------------


def test_no_record_means_no_supersessions(tmp_path: Path) -> None:
    assert not read_supersessions(make_kb(tmp_path))


def test_records_survive_a_round_trip(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    record = a_record("mgp-new", "mgp-old")

    write_supersessions(paths, [record])

    assert read_supersessions(paths) == [record]
    loaded = json.loads(supersessions_path(paths).read_text())
    assert loaded["supersessions"][0]["successor"] == "mgp-new"


def test_putting_a_record_replaces_the_one_for_the_same_successor(
    tmp_path: Path,
) -> None:
    """Re-measuring a deck must not leave two verdicts about it."""
    paths = make_kb(tmp_path)
    put(paths, a_record("mgp-new", "mgp-old"))
    put(paths, a_record("mgp-new", "mgp-old", "mgp-older"))

    (only,) = read_supersessions(paths)
    assert only.predecessors == ("mgp-old", "mgp-older")


def test_an_unreadable_record_reads_as_none(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    supersessions_path(paths).write_text("{not json", encoding="utf-8")

    assert not read_supersessions(paths)


# --- lineage ----------------------------------------------------------------


def test_lineage_names_the_successor_of_each_predecessor(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    write_supersessions(paths, [a_record("mgp-new", "mgp-old")])

    found = lineage(paths)

    assert found.successors_of("mgp-old") == ("mgp-new",)
    assert found.successors_of("mgp-new") == ()


def test_a_rejected_record_supersedes_nothing(tmp_path: Path) -> None:
    """Rejecting puts the old deck back on top without touching the index."""
    paths = make_kb(tmp_path)
    write_supersessions(paths, [a_record("mgp-new", "mgp-old", decided=REJECTED)])

    assert lineage(paths).successors_of("mgp-old") == ()


def test_an_accepted_record_still_supersedes(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    write_supersessions(paths, [a_record("mgp-new", "mgp-old", decided=ACCEPTED)])

    assert lineage(paths).successors_of("mgp-old") == ("mgp-new",)


def test_new_material_supersedes_nothing(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    write_supersessions(paths, [a_record("mgp-new")])

    assert not lineage(paths).successor_of


def test_one_old_deck_split_in_two_has_two_successors(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    write_supersessions(
        paths, [a_record("mgp-a", "mgp-old"), a_record("mgp-b", "mgp-old")]
    )

    assert lineage(paths).successors_of("mgp-old") == ("mgp-a", "mgp-b")


def test_lineage_knows_the_vintage_of_every_intake_source(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    write_intake(
        paths,
        [
            {"path": "courses/MGP/raw/slides/t3/flows.pdf", "kind": "slides"},
            {
                "path": "courses/MGP/raw/slides/tema-3/flows.pdf",
                "kind": "slides",
                "year": "2026-27",
            },
        ],
    )

    found = lineage(paths)

    assert found.vintage_of("mgp-slides-t3-flows") == "2025-26"
    assert found.vintage_of("mgp-slides-tema-3-flows") == "2026-27"
    assert found.vintage_of("bishop") == ""


# --- the manifest -----------------------------------------------------------


def test_the_manifest_records_which_supersessions_ranked_the_index(
    tmp_path: Path,
) -> None:
    """Ranking reads a record outside the index; "why did retrieval change?"
    has no answer unless the manifest says which record that was."""
    paths = make_kb(tmp_path)
    write_supersessions(paths, [a_record("mgp-new", "mgp-old")])

    write_manifest(paths, Manifest())

    stamped = read_manifest(paths).supersessions_sha256
    assert stamped
    assert stamped == fingerprint(paths)


def test_no_record_fingerprints_as_empty(tmp_path: Path) -> None:
    assert fingerprint(make_kb(tmp_path)) == ""
