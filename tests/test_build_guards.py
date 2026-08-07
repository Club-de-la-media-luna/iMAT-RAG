from __future__ import annotations

from pathlib import Path

from imat_rag.config import Paths
from imat_rag.inbox import add_entry
from imat_rag.index.embed import EmbedConfig
from imat_rag.index.search import build


class FakeEncoder:
    dimensions = 4

    def encode(self, sentences: object, **_: object) -> object:
        return [[0.0, 0.0, 0.0, 0.0] for _ in list(sentences)]  # type: ignore[call-overload]


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def test_indexing_nothing_is_an_empty_index_not_a_lancedb_error(
    tmp_path: Path,
) -> None:
    """`rag index` before `rag chunk` should say so, not raise from the driver."""
    paths = make_kb(tmp_path / "kb")

    assert build(paths, EmbedConfig(), FakeEncoder()) == (0, 0)


def test_a_section_name_inside_an_entry_title_is_not_the_section(
    tmp_path: Path,
) -> None:
    """`### Bibliografía básica` contains `## Bibliografía básica` as a substring.

    Matching it as one splits inside the entry, leaving a stray `#` behind and
    filing the new book in the wrong place.
    """
    ledger = "# GI\n\n### Bibliografía básica y sus fuentes\n- EN: ✅ `old.pdf`\n"

    updated = add_entry(ledger, "Bibliografía básica", "A Book", "new.pdf")

    assert "### Bibliografía básica y sus fuentes" in updated
    assert "## Bibliografía básica\n" in updated
    assert "#\n" not in updated
