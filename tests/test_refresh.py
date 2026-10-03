from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from imat_rag.config import Paths
from imat_rag.index import lance
from imat_rag.index.embed import EmbedConfig
from imat_rag.index.search import build
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.store import (
    BookChunks,
    Manifest,
    read_manifest,
    write_chunks,
    write_manifest,
)
from imat_rag.refresh import (
    CHANGED,
    NEW,
    REVISED,
    SAME,
    NotInIntake,
    NotReady,
    accept,
    best_matches,
    classify,
    compare,
    diagnose,
    find_predecessors,
    grade,
    out_of_order,
    pending,
    refresh,
    reject,
    same_text,
)
from imat_rag.supersession import ACCEPTED, REJECTED, REVIEW, read_supersessions

DIMENSIONS = 24


def unit(i: int) -> list[float]:
    """Slide `i` as a hand-built unit vector: no model, no download."""
    return [1.0 if j == i else 0.0 for j in range(DIMENSIONS)]


def deck(*slides: int) -> list[list[float]]:
    return [unit(i) for i in slides]


# --- grading on synthetic decks ---------------------------------------------


def test_an_identical_deck_is_the_same() -> None:
    result = compare(deck(0, 1, 2, 3), {"old": deck(0, 1, 2, 3)})

    assert result.grade == SAME
    assert (result.added, result.dropped) == (0.0, 0.0)
    assert result.predecessors == ("old",)


def test_one_slide_added_is_a_revision() -> None:
    old = list(range(10))
    result = compare(deck(*old, 20), {"old": deck(*old)})

    assert result.grade == REVISED
    assert result.added == pytest.approx(1 / 11)
    assert result.dropped == 0.0


def test_half_the_deck_replaced_is_a_change() -> None:
    result = compare(deck(0, 1, 2, 3, 14, 15, 16, 17), {"old": deck(*range(8))})

    assert result.grade == CHANGED
    assert result.added == pytest.approx(0.5)
    assert result.dropped == pytest.approx(0.5)


def test_reordering_alone_changes_nothing() -> None:
    """Coverage is order-blind: a reshuffle is reported, never graded."""
    result = compare(deck(3, 2, 1, 0), {"old": deck(0, 1, 2, 3)})

    assert result.grade == SAME
    assert out_of_order(result.successor_best)


def test_an_unrelated_deck_is_new() -> None:
    result = compare(deck(10, 11, 12), {"old": deck(0, 1, 2)})

    assert result.grade == NEW
    assert result.predecessors == ()


def test_nothing_to_compare_against_is_new() -> None:
    assert compare(deck(0, 1), {}).grade == NEW


def test_best_match_is_the_closest_child_of_the_other_deck() -> None:
    best = best_matches(deck(0, 5), deck(5, 0, 9))

    assert best == [(pytest.approx(1.0), 1), (pytest.approx(1.0), 0)]


def test_best_match_against_nothing_matches_nothing() -> None:
    assert best_matches(deck(0), []) == [(0.0, -1)]


# --- predecessors -----------------------------------------------------------


def test_one_old_deck_split_in_two_is_a_predecessor_of_both() -> None:
    old = {"old": deck(0, 1, 2, 3, 4, 5)}

    assert find_predecessors(deck(0, 1, 2), old) == ["old"]
    assert find_predecessors(deck(3, 4, 5), old) == ["old"]


def test_two_old_decks_merged_are_both_predecessors() -> None:
    old = {"first": deck(0, 1, 2), "second": deck(3, 4, 5), "other": deck(9)}

    assert find_predecessors(deck(0, 1, 2, 3, 4, 5), old) == ["first", "second"]


def test_a_deck_covering_too_little_is_not_a_predecessor() -> None:
    """One shared slide in ten is a quotation, not a lineage."""
    old = {"old": deck(0, 20, 21)}

    assert not find_predecessors(deck(*range(10)), old)


def test_a_renamed_topic_does_not_hide_a_predecessor() -> None:
    """`t3-flow-models` became `tema-3`; the vectors are what decide."""
    old = {"mgp-slides-t3-flow-models-flows": deck(0, 1, 2)}

    found = find_predecessors(deck(0, 1, 2), old, topics={}, topic="tema-3")

    assert found == ["mgp-slides-t3-flow-models-flows"]


def test_the_topic_breaks_a_tie_between_predecessors() -> None:
    old = {"b-elsewhere": deck(0, 1), "a-same-topic": deck(0, 1)}

    found = find_predecessors(
        deck(0, 1),
        old,
        topics={"b-elsewhere": "t1", "a-same-topic": "tema-3"},
        topic="tema-3",
    )

    assert found == ["a-same-topic", "b-elsewhere"]


# --- calibration ------------------------------------------------------------


@pytest.mark.parametrize(
    ("new_covered", "old_covered", "expected"),
    [
        (0.73, 0.97, REVISED),  # MP tema-2 parte1-incompleto -> parte1
        (0.61, 1.00, CHANGED),  # MGP t3 flujoscontinuos -> flujoscontinuosii
        (0.00, 0.00, NEW),  # MP tema-2 parte1 -> parte2
        (0.00, 0.00, NEW),  # MGP t1 slides -> t1 repaso
        (0.00, 0.00, NEW),  # MGP flows -> MP tema-2 parte1
    ],
)
def test_the_measured_pairs_grade_as_adr_0009_expects(
    new_covered: float, old_covered: float, expected: str
) -> None:
    """The five pairs measured on the published index, 2026-10-03."""
    assert classify(new_covered, old_covered).grade == expected


def test_the_grade_boundaries_are_inclusive() -> None:
    assert grade(0.05, 0.05, has_predecessor=True) == SAME
    assert grade(0.30, 0.30, has_predecessor=True) == REVISED
    assert grade(0.31, 0.0, has_predecessor=True) == CHANGED
    assert grade(0.0, 0.0, has_predecessor=False) == NEW


# --- the text stage ---------------------------------------------------------


def a_chunk(slug: str, chunk_id: str, text: str, **extra: Any) -> Chunk:
    fields: dict[str, Any] = {
        "chunk_id": chunk_id,
        "book_slug": slug,
        "breadcrumb": f"{slug} > Section",
        "text": text,
        "page_start": 1,
        "page_end": 1,
        "parent_id": f"{slug}-p",
        "courses": ("MGP",),
        "source_tier": 5,
    }
    fields.update(extra)
    return Chunk(**fields)


def test_text_identical_up_to_case_and_spacing_is_the_same_deck() -> None:
    """No vectors are needed to see that nothing changed."""
    new = [a_chunk("new", "n1", "Normalising  flows"), a_chunk("new", "n2", "Jacobian")]
    old = [a_chunk("old", "o1", "normalising flows"), a_chunk("old", "o2", "jacobian ")]

    assert same_text(new, {"old": old, "other": old[:1]}) == "old"


def test_one_changed_word_is_not_the_same_text() -> None:
    new = [a_chunk("new", "n1", "normalising flows")]
    old = [a_chunk("old", "o1", "normalizing flows")]

    assert same_text(new, {"old": old}) == ""


# --- diagnosis --------------------------------------------------------------


def test_a_diagnosis_groups_what_was_added_and_dropped_by_section() -> None:
    new = [
        a_chunk("new", "n1", "flows", breadcrumb="T3 > 3.1 Flows"),
        a_chunk(
            "new",
            "n2",
            "$$\\log p(x) = \\log p(z)$$",
            breadcrumb="T3 > 3.2 Normalising flows",
            page_start=6,
            page_end=6,
        ),
        a_chunk(
            "new",
            "n3",
            "$$\\det J$$",
            breadcrumb="T3 > 3.2 Normalising flows",
            page_start=7,
            page_end=7,
        ),
    ]
    old = [
        a_chunk("old", "o1", "flows", breadcrumb="T3 > 3.1 Flows"),
        a_chunk("old", "o2", "| a | b |", breadcrumb="T3 > 3.9 Appendix"),
    ]
    result = compare(deck(0, 1, 2), {"old": deck(0, 9)})

    report = diagnose("new", new, old, result)

    assert "# Refresh: new" in report
    assert "T3 > 3.2 Normalising flows, pp. 6-7 · 2 children · equations" in report
    assert "T3 > 3.9 Appendix" in report and "tables" in report
    assert "T3 > 3.1 Flows" not in report.split("## Added")[1].split("## Dropped")[0]


# --- the pipeline -----------------------------------------------------------


class SlideEncoder:
    """Each slide word is one axis, so every child embeds as a unit vector."""

    vocabulary = tuple(f"s{i}" for i in range(DIMENSIONS))

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, sentences: Any, **_: Any) -> Any:
        self.calls += 1
        rows = []
        for sentence in sentences:
            words = set(str(sentence).lower().split())
            rows.append([1.0 if term in words else 0.0 for term in self.vocabulary])
        return rows


OLD_PATH = "courses/MGP/raw/slides/t3-flow-models/flujos.pdf"
NEW_PATH = "courses/MGP/raw/slides/tema-3/flujos.pdf"
OLD_SLUG = "mgp-slides-t3-flow-models-flujos"
NEW_SLUG = "mgp-slides-tema-3-flujos"


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def slides(slug: str, *words: str) -> list[Chunk]:
    parent = a_chunk(
        slug, f"{slug}-p", " ".join(words), parent_id="", is_parent=True, page_end=9
    )
    return [parent] + [
        a_chunk(slug, f"{slug}-{n}", word, page_start=n, page_end=n)
        for n, word in enumerate(words, start=1)
    ]


def seed(paths: Paths, old: tuple[str, ...], new: tuple[str, ...]) -> None:
    entries: list[dict[str, object]] = [
        {"path": OLD_PATH, "course": "MGP", "kind": "slides", "topic": "t3-flow-models"},
        {
            "path": NEW_PATH,
            "course": "MGP",
            "kind": "slides",
            "topic": "tema-3",
            "year": "2026-27",
        },
    ]
    (paths.kb_root / "intake.json").write_text(
        json.dumps({"archive": "moodle", "files": entries}), encoding="utf-8"
    )
    write_chunks(paths, OLD_SLUG, slides(OLD_SLUG, *old))
    write_chunks(paths, NEW_SLUG, slides(NEW_SLUG, *new))
    write_manifest(
        paths,
        Manifest(
            books=[
                BookChunks(
                    slug=OLD_SLUG,
                    source_sha256="a",
                    stage_key="k",
                    chunks=len(old) + 1,
                    parents=1,
                    children=len(old),
                    courses=("MGP",),
                )
            ]
        ),
    )
    # Last year's index, as published: the old deck only.
    build(paths, EmbedConfig(), SlideEncoder())
    manifest = read_manifest(paths)
    manifest.books.append(
        BookChunks(
            slug=NEW_SLUG,
            source_sha256="b",
            stage_key="k",
            chunks=len(new) + 1,
            parents=1,
            children=len(new),
            courses=("MGP",),
        )
    )
    write_manifest(paths, manifest)


def test_a_revised_deck_supersedes_its_predecessor(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    old = tuple(f"s{i}" for i in range(10))
    seed(paths, old, (*old, "s20"))

    done = refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    assert done.record.grade == REVISED
    assert done.record.predecessors == (OLD_SLUG,)
    assert done.record.measured is not None
    assert done.record.measured.successor_children == 11
    assert read_supersessions(paths) == [done.record]


def test_refreshing_appends_the_new_deck_to_the_index(tmp_path: Path) -> None:
    """Append, not rebuild: the old deck's rows are left as they were."""
    paths = make_kb(tmp_path)
    old = tuple(f"s{i}" for i in range(10))
    seed(paths, old, (*old, "s20"))

    refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    table = lance.connect(paths.index).open_table(lance.CHILDREN)
    slugs = [row["book_slug"] for row in table.to_arrow().to_pylist()]
    assert slugs.count(OLD_SLUG) == 10
    assert slugs.count(NEW_SLUG) == 11
    parents = lance.connect(paths.index).open_table(lance.PARENTS)
    assert parents.count_rows() == 2


def test_refreshing_twice_does_not_index_the_deck_twice(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    old = tuple(f"s{i}" for i in range(10))
    seed(paths, old, (*old, "s20"))

    refresh(paths, NEW_SLUG, encoder=SlideEncoder())
    refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    table = lance.connect(paths.index).open_table(lance.CHILDREN)
    assert table.count_rows() == 21
    assert len(read_supersessions(paths)) == 1


def test_a_changed_deck_waits_for_review_and_writes_a_report(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths, ("s0", "s1", "s2", "s3"), ("s0", "s1", "s14", "s15"))

    done = refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    assert done.record.grade == CHANGED
    assert done.record.decided == REVIEW
    assert done.report is not None
    assert done.report == paths.derived / "refresh" / f"{NEW_SLUG}.md"
    assert "## Added" in done.report.read_text(encoding="utf-8")


def test_a_lightly_revised_deck_writes_no_report_unless_asked(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    old = tuple(f"s{i}" for i in range(10))
    seed(paths, old, (*old, "s20"))

    quiet = refresh(paths, NEW_SLUG, encoder=SlideEncoder())
    asked = refresh(paths, NEW_SLUG, encoder=SlideEncoder(), report=True)

    assert quiet.report is None
    assert asked.report is not None and asked.report.is_file()


def test_an_identical_deck_is_graded_without_measuring_vectors(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths, ("s0", "s1"), ("s0", "s1"))

    done = refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    assert done.record.grade == SAME
    assert done.record.measured is None


def test_predecessors_come_from_the_same_course_only(tmp_path: Path) -> None:
    """The same slide in another course is that course's deck, not this one's."""
    paths = make_kb(tmp_path)
    seed(paths, ("s0", "s1"), ("s0", "s1", "s2"))
    intake = json.loads((paths.kb_root / "intake.json").read_text())
    intake["files"][0]["course"] = "MP"
    (paths.kb_root / "intake.json").write_text(json.dumps(intake))

    done = refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    assert done.record.grade == NEW
    assert done.record.predecessors == ()


def test_the_record_is_fingerprinted_in_the_manifest(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths, ("s0", "s1"), ("s0", "s1", "s2"))

    refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    assert read_manifest(paths).supersessions_sha256


def test_a_source_the_intake_never_took_is_refused(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)

    with pytest.raises(NotInIntake):
        refresh(paths, "nowhere", encoder=SlideEncoder())


def test_a_deck_not_yet_extracted_is_refused_with_the_next_step(
    tmp_path: Path,
) -> None:
    paths = make_kb(tmp_path)
    seed(paths, ("s0",), ("s0",))
    (paths.chunks / f"{NEW_SLUG}.jsonl").unlink()

    with pytest.raises(NotReady, match="rag extract"):
        refresh(paths, NEW_SLUG, encoder=SlideEncoder())


def test_pending_lists_this_years_decks_with_no_verdict(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths, ("s0", "s1"), ("s0", "s1", "s2"))

    assert pending(paths, "2026-27") == [NEW_SLUG]
    refresh(paths, NEW_SLUG, encoder=SlideEncoder())
    assert not pending(paths, "2026-27")


def test_accepting_confirms_a_record_and_rejecting_keeps_the_verdict(
    tmp_path: Path,
) -> None:
    """A rejection must stick, or the next bulk refresh would propose it again."""
    paths = make_kb(tmp_path)
    seed(paths, ("s0", "s1", "s2", "s3"), ("s0", "s1", "s14", "s15"))
    refresh(paths, NEW_SLUG, encoder=SlideEncoder())

    assert accept(paths, NEW_SLUG)
    assert read_supersessions(paths)[0].decided == ACCEPTED
    assert reject(paths, NEW_SLUG)
    assert read_supersessions(paths)[0].decided == REJECTED
    assert not pending(paths, "2026-27")
    assert not accept(paths, "nothing-recorded")
