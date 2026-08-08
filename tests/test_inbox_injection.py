from __future__ import annotations

from imat_rag.inbox import Rejected, add_entry, parse_drop
from imat_rag.ingest.catalogue import parse_ledger


def test_a_filename_carrying_a_newline_is_refused() -> None:
    """The filename is written into a Markdown ledger inside backticks.

    A newline closes the entry and opens whatever the contributor wants, and
    `catalogue.collect` reads that ledger to decide what gets indexed. So the
    forgery would not merely look wrong, it would be acted on.
    """
    parsed = parse_drop("GI/basic/x.pdf\n### Forged\n- EN: OK a.pdf")

    assert isinstance(parsed, Rejected)


def test_a_filename_carrying_a_backtick_is_refused() -> None:
    """Backticks delimit the path in an entry; one inside ends it early."""
    assert isinstance(parse_drop("GI/basic/a`b.pdf"), Rejected)


def test_an_ordinary_filename_still_passes() -> None:
    parsed = parse_drop("GI/basic/murphy-k-p-probabilistic-ml-2022.pdf")

    assert not isinstance(parsed, Rejected)


def test_a_title_cannot_forge_an_entry_either() -> None:
    """The title comes from a sidecar the contributor also writes.

    Asserted against the ledger parser rather than the text, because that is
    what decides which files get indexed: the forged line may survive as
    characters, so long as it cannot be read back as a second entry.
    """
    forged = "A Book\n### Forged\n- EN: ✅ `/etc/passwd`"

    updated = add_entry(
        "# GI\n\n## Bibliografía básica\n\n", "Bibliografía básica", forged, "ok.pdf"
    )

    entries = parse_ledger(updated, "GI")
    assert [entry.filename for entry in entries] == ["ok.pdf"]
