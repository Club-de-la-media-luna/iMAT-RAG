from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from imat_rag.config import Paths
from imat_rag.index.embed import EmbedConfig
from imat_rag.index.search import Hit, build, fetch, search
from imat_rag.ingest.chunk import Chunk
from imat_rag.ingest.store import BookChunks, Manifest, write_chunks, write_manifest
from imat_rag.supersession import REJECTED, Supersession, write_supersessions

OLD = "mgp-slides-t3-flujos"
NEW = "mgp-slides-tema-3-flujos"


class FakeEncoder:
    """Word overlap, so identical slides embed identically."""

    vocabulary = (
        "mixture models expectation maximisation gaussian curvature jacobian"
    ).split()

    def encode(self, sentences: Any, **_: Any) -> Any:
        rows = []
        for sentence in sentences:
            words = set(str(sentence).lower().split())
            rows.append([1.0 if term in words else 0.0 for term in self.vocabulary])
        return rows


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def a_chunk(slug: str, chunk_id: str, text: str, **extra: Any) -> Chunk:
    fields: dict[str, Any] = {
        "chunk_id": chunk_id,
        "book_slug": slug,
        "breadcrumb": "Flows",
        "text": text,
        "page_start": 3,
        "page_end": 3,
        "parent_id": f"{slug}-p",
        "courses": ("MGP",),
        "source_tier": 5,
    }
    fields.update(extra)
    return Chunk(**fields)


def deck(slug: str, *texts: str) -> list[Chunk]:
    parent = a_chunk(slug, f"{slug}-p", " ".join(texts), parent_id="", is_parent=True)
    children = [
        a_chunk(slug, f"{slug}-{n}", text, page_start=n, page_end=n)
        for n, text in enumerate(texts, start=1)
    ]
    return [parent, *children]


def seed(paths: Paths, *, record: bool = True, decided: str = "auto") -> None:
    """Last year's deck taught mixtures and curvature; this year's cut curvature."""
    old = deck(OLD, "mixture models", "gaussian curvature")
    new = deck(NEW, "mixture models", "jacobian")
    write_chunks(paths, OLD, old)
    write_chunks(paths, NEW, new)
    write_manifest(
        paths,
        Manifest(
            books=[
                BookChunks(
                    slug=slug,
                    source_sha256=slug,
                    stage_key="k",
                    chunks=3,
                    parents=1,
                    children=2,
                    courses=("MGP",),
                )
                for slug in (OLD, NEW)
            ]
        ),
    )
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
    if record:
        write_supersessions(
            paths,
            [
                Supersession(
                    successor=NEW,
                    predecessors=(OLD,),
                    grade="changed",
                    added=0.5,
                    dropped=0.5,
                    decided=decided,
                )
            ],
        )
    build(paths, EmbedConfig(), FakeEncoder())


def slugs(hits: list[Hit]) -> list[str]:
    return [hit.book_slug for hit in hits]


def test_the_successor_says_it_and_the_predecessor_is_not_repeated(
    tmp_path: Path,
) -> None:
    """Both decks hold the same slide; only the newer one comes back."""
    paths = make_kb(tmp_path)
    seed(paths)

    hits = search(paths, "mixture models", limit=1, expand=False, encoder=FakeEncoder())

    assert slugs(hits) == [NEW]
    assert hits[0].vintage == "2026-27"
    assert hits[0].superseded_by is None


def test_a_slide_only_the_predecessor_has_is_still_returned_flagged(
    tmp_path: Path,
) -> None:
    """Cut material may still be the only explanation; it must say it was cut."""
    paths = make_kb(tmp_path)
    seed(paths)

    hits = search(
        paths, "gaussian curvature", limit=1, expand=False, encoder=FakeEncoder()
    )

    assert slugs(hits) == [OLD]
    assert hits[0].vintage == "2025-26"
    assert hits[0].superseded_by == NEW
    assert "(2025-26, superseded by 2026-27)" in hits[0].citation


def test_a_predecessor_hit_is_demoted_below_its_successor(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)

    hits = search(
        paths,
        "mixture models gaussian curvature jacobian",
        limit=4,
        expand=False,
        encoder=FakeEncoder(),
    )

    ranked = slugs(hits)
    assert ranked.index(NEW) < ranked.index(OLD)
    old = next(hit for hit in hits if hit.book_slug == OLD)
    assert old.superseded_by == NEW


def test_removing_the_record_restores_the_old_deck(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths, record=False)

    hits = search(paths, "mixture models", limit=4, expand=False, encoder=FakeEncoder())

    assert set(slugs(hits)) >= {OLD, NEW}
    assert all(hit.superseded_by is None for hit in hits)


def test_a_rejected_record_ranks_as_though_it_were_absent(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths, decided=REJECTED)

    hits = search(paths, "mixture models", limit=4, expand=False, encoder=FakeEncoder())

    assert OLD in slugs(hits)


def test_an_expanded_predecessor_section_carries_the_flag(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)

    hits = search(paths, "gaussian curvature", limit=1, encoder=FakeEncoder())

    assert hits[0].chunk_id == f"{OLD}-p"
    assert hits[0].superseded_by == NEW


def test_fetching_a_superseded_chunk_says_so(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    seed(paths)

    found = fetch(paths, f"{OLD}-2")

    assert found is not None
    assert found.chunk.superseded_by == NEW
    assert found.chunk.vintage == "2025-26"
