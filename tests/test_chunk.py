from __future__ import annotations

from imat_rag.ingest.chunk import (
    chunk_book,
    chunk_id,
    chunk_section,
    split_pieces,
    split_sections,
)

MARKDOWN = """\
<!--page:0-->

# 9. Mixture Models and EM

Opening prose about latent variables.

<!--page:1-->

## 9.1. K-means Clustering

We begin by considering the problem of identifying groups.

$$J = \\sum_{n=1}^{N} r_{nk}\\|x_n - \\mu_k\\|^2 \\tag{9.1}$$

More prose after the equation.

<!--page:2-->

### 9.1.1 Image segmentation

Applying K-means to pixels.
"""


# --- pieces and pages -------------------------------------------------------


def test_page_anchors_set_the_page_and_are_stripped() -> None:
    pieces = split_pieces(MARKDOWN)

    assert all("<!--page:" not in piece.text for piece in pieces)
    assert pieces[0].page == 0
    assert any(p.page == 2 for p in pieces)


def test_equations_are_atomic() -> None:
    pieces = split_pieces(MARKDOWN)
    equation = next(p for p in pieces if p.text.startswith("$$"))

    assert equation.atomic is True


def test_tables_figures_and_code_are_atomic() -> None:
    md = "| a | b |\n|---|---|\n\n![cap](p1-fig1.jpg)\n\n```py\nx=1\n```"
    pieces = split_pieces(md)

    assert [p.atomic for p in pieces] == [True, True, True]


def test_prose_is_not_atomic() -> None:
    assert split_pieces("Just a paragraph.")[0].atomic is False


# --- sections and breadcrumbs -----------------------------------------------


def test_breadcrumbs_follow_the_heading_tree() -> None:
    sections = split_sections(MARKDOWN, "Bishop PRML")
    crumbs = [s.breadcrumb for s in sections]

    assert "Bishop PRML > 9. Mixture Models and EM" in crumbs
    assert "Bishop PRML > 9. Mixture Models and EM > 9.1. K-means Clustering" in crumbs
    assert (
        "Bishop PRML > 9. Mixture Models and EM > 9.1. K-means Clustering > "
        "9.1.1 Image segmentation" in crumbs
    )


def test_a_sibling_heading_replaces_rather_than_nests() -> None:
    md = "# A\n\ntext a\n\n## B\n\ntext b\n\n## C\n\ntext c\n"
    crumbs = [s.breadcrumb for s in split_sections(md, "Book")]

    assert "Book > A > C" in crumbs
    assert "Book > A > B > C" not in crumbs


def test_returning_to_a_shallower_level_truncates_the_trail() -> None:
    md = "# A\n\na\n\n## B\n\nb\n\n### C\n\nc\n\n# D\n\nd\n"
    crumbs = [s.breadcrumb for s in split_sections(md, "Book")]

    assert "Book > D" in crumbs


def test_sections_report_their_page_range() -> None:
    sections = split_sections(MARKDOWN, "Bishop PRML")
    last = sections[-1]

    assert last.pages == (2, 2)


def test_content_before_any_heading_still_becomes_a_section() -> None:
    sections = split_sections("Preamble text.\n", "Book")

    assert sections[0].breadcrumb == "Book"
    assert "Preamble" in sections[0].text


# --- chunk identity ---------------------------------------------------------


def test_identical_content_yields_identical_ids() -> None:
    """Two contributors ingesting the same deck must converge."""
    assert chunk_id("b", 1, 2, "text") == chunk_id("b", 1, 2, "text")


def test_different_text_yields_different_ids() -> None:
    assert chunk_id("b", 1, 2, "one") != chunk_id("b", 1, 2, "two")


def test_different_pages_yield_different_ids() -> None:
    assert chunk_id("b", 1, 2, "text") != chunk_id("b", 3, 4, "text")


def test_ids_do_not_depend_on_position_in_the_document() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")
    again = chunk_book(MARKDOWN, "bishop", "Bishop PRML")

    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in again]


# --- parents and children ---------------------------------------------------


def test_every_child_points_at_a_parent_that_exists() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")
    parents = {c.chunk_id for c in chunks if c.is_parent}
    children = [c for c in chunks if not c.is_parent]

    assert children
    assert all(child.parent_id in parents for child in children)


def test_parents_are_not_themselves_children() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")

    assert all(c.parent_id == "" for c in chunks if c.is_parent)


def test_an_equation_is_never_split_across_chunks() -> None:
    """Half a derivation is not half as useful."""
    long_equation = "$$" + " + ".join(f"x_{i}" for i in range(500)) + "$$"
    md = f"# S\n\nprose\n\n{long_equation}\n\nmore prose\n"

    chunks = chunk_book(md, "b", "Book")
    bodies = [c.text for c in chunks if not c.is_parent]

    assert any(long_equation in body for body in bodies)


def test_children_stay_near_the_budget_when_prose_allows() -> None:
    md = "# S\n\n" + "\n\n".join("word " * 100 for _ in range(20))

    children = [c for c in chunk_book(md, "b", "Book") if not c.is_parent]

    assert len(children) > 1
    assert all(c.tokens <= 500 for c in children)


def test_pages_are_carried_onto_chunks() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")

    assert all(c.page_start <= c.page_end for c in chunks)
    assert max(c.page_end for c in chunks) == 2


# --- what gets embedded -----------------------------------------------------


def test_the_breadcrumb_is_prefixed_to_the_embedded_text() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")
    child = next(c for c in chunks if not c.is_parent and "K-means" not in c.text)

    assert child.embedding_text.startswith(child.breadcrumb)
    assert child.text in child.embedding_text


def test_courses_and_tier_are_carried_onto_every_chunk() -> None:
    chunks = chunk_book(
        MARKDOWN, "murphy", "Murphy", courses=("IAP", "MGP"), source_tier=2
    )

    assert all(c.courses == ("IAP", "MGP") for c in chunks)
    assert all(c.source_tier == 2 for c in chunks)


def test_a_section_shorter_than_the_budget_yields_one_parent_and_one_child() -> None:
    chunks = chunk_section(split_sections("# S\n\nshort text\n", "Book")[0], "b")

    assert sum(1 for c in chunks if c.is_parent) == 1
    assert sum(1 for c in chunks if not c.is_parent) == 1


def test_a_parent_and_its_only_child_do_not_collide() -> None:
    """A short section gives both the same text and pages."""
    chunks = chunk_section(split_sections("# S\n\nshort\n", "Book")[0], "b")

    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_every_chunk_id_in_a_book_is_unique() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")

    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_no_child_points_at_itself() -> None:
    chunks = chunk_book(MARKDOWN, "bishop", "Bishop PRML")

    assert all(c.parent_id != c.chunk_id for c in chunks)


def test_stray_inline_sub_tags_are_unwrapped() -> None:
    """mineru renders 'diagonalising' as di<sub>agona</sub>li<sub>s</sub>ing."""
    pieces = split_pieces("The di<sub>agona</sub>li<sub>s</sub>ing matrix.")

    assert pieces[0].text == "The diagonalising matrix."


def test_atomic_blocks_keep_their_markup() -> None:
    html = "<table><tr><td>a<sub>1</sub></td></tr></table>"

    assert split_pieces(html)[0].text == html
