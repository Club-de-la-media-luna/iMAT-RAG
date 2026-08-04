from __future__ import annotations

from imat_rag.ingest.assemble import (
    Outline,
    OutlineEntry,
    assemble,
    heading_depth,
    html_table_to_markdown,
    is_margin_note,
    page_span,
    parse_blocks,
)

RECORDS = [
    {"type": "text", "text": "Opening paragraph.", "page_idx": 0},
    {"type": "aside_text", "text": "Section 9.2", "page_idx": 0},
    {"type": "page_number", "text": "443", "page_idx": 0},
    {"type": "text", "text": "9.1. K-means Clustering", "text_level": 2, "page_idx": 1},
    {"type": "equation", "text": "$$J = \\sum r_{nk}\\tag{9.1}$$", "page_idx": 1},
    {"type": "header", "text": "9. MIXTURE MODELS", "page_idx": 1},
    {
        "type": "image",
        "img_path": "images/abc.jpg",
        "image_caption": ["Figure 9.1"],
        "page_idx": 2,
    },
]


def test_margin_notes_and_running_furniture_are_dropped() -> None:
    """The defect that corrupts prose in both marker and docling."""
    out = assemble(parse_blocks(RECORDS))

    assert "Section 9.2" not in out
    assert "443" not in out
    assert "9. MIXTURE MODELS" not in out
    assert "Opening paragraph." in out


def test_a_page_anchor_precedes_each_new_page() -> None:
    out = assemble(parse_blocks(RECORDS))

    assert out.index("<!--page:0-->") < out.index("Opening paragraph.")
    assert out.index("<!--page:1-->") < out.index("K-means")
    assert out.count("<!--page:1-->") == 1


def test_pages_with_only_discarded_blocks_emit_no_anchor() -> None:
    records = [
        {"type": "text", "text": "Body.", "page_idx": 0},
        {"type": "page_number", "text": "12", "page_idx": 1},
        {"type": "text", "text": "More.", "page_idx": 2},
    ]

    out = assemble(parse_blocks(records))

    assert "<!--page:1-->" not in out


def test_equations_pass_through_untouched() -> None:
    out = assemble(parse_blocks(RECORDS))

    assert "$$J = \\sum r_{nk}\\tag{9.1}$$" in out


def test_figures_render_with_caption_and_mapped_name() -> None:
    out = assemble(
        parse_blocks(RECORDS), figure_names={"images/abc.jpg": "p2-fig1.jpg"}
    )

    assert "![Figure 9.1](p2-fig1.jpg)" in out


def test_captions_given_as_the_string_bracket_pair_are_treated_as_empty() -> None:
    blocks = parse_blocks(
        [{"type": "image", "img_path": "i.jpg", "image_caption": "[]", "page_idx": 0}]
    )

    assert blocks[0].caption == ""


# --- heading depth ----------------------------------------------------------


def test_depth_comes_from_the_numbering_when_there_is_no_outline() -> None:
    assert heading_depth("9. Mixture Models and EM") == 1
    assert heading_depth("9.1. K-means Clustering") == 2
    assert heading_depth("9.1.1 Image segmentation") == 3
    assert heading_depth("9.3.4 EM for Bayesian linear regression") == 3


def test_unnumbered_headings_default_to_section_depth() -> None:
    assert heading_depth("Exercises") == 2
    assert heading_depth("The General EM Algorithm") == 2


def test_the_outline_wins_over_the_numbering() -> None:
    outline = Outline(
        [
            OutlineEntry(title="Exercises", depth=1, page=0),
            OutlineEntry(title="9.1. K-means Clustering", depth=4, page=0),
        ]
    )

    assert heading_depth("Exercises", outline) == 1
    assert heading_depth("9.1. K-means Clustering", outline) == 4


def test_outline_lookup_ignores_case() -> None:
    outline = Outline([OutlineEntry(title="Exercises", depth=1, page=0)])

    assert heading_depth("exercises", outline) == 1


def test_depth_becomes_markdown_hashes() -> None:
    records = [
        {"type": "text", "text": "9. Mixture Models", "text_level": 2, "page_idx": 0},
        {"type": "text", "text": "9.1. K-means", "text_level": 2, "page_idx": 0},
        {"type": "text", "text": "9.1.1 Segmentation", "text_level": 2, "page_idx": 0},
    ]

    out = assemble(parse_blocks(records))

    assert "# 9. Mixture Models" in out
    assert "## 9.1. K-means" in out
    assert "### 9.1.1 Segmentation" in out


def test_heading_depth_is_capped_at_six_hashes() -> None:
    records = [
        {"type": "text", "text": "1.2.3.4.5.6.7.8 Deep", "text_level": 2, "page_idx": 0}
    ]

    assert "###### 1.2.3.4.5.6.7.8 Deep" in assemble(parse_blocks(records))


def test_a_number_with_no_following_text_is_not_a_heading_number() -> None:
    assert heading_depth("9.") == 2


# --- page span --------------------------------------------------------------


def test_page_span_reports_the_range(tmp_path: object) -> None:
    assert page_span(assemble(parse_blocks(RECORDS))) == (0, 2)


def test_page_span_of_empty_markdown_is_zero() -> None:
    assert page_span("no anchors here") == (0, 0)


# --- margin notes mineru mistypes as prose ----------------------------------


def test_cross_reference_only_blocks_are_margin_notes() -> None:
    """mineru types most as aside_text, but ~8 of 44 leak through as text."""
    leaked = parse_blocks(
        [
            {"type": "text", "text": "Exercise 9.1", "page_idx": 2},
            {"type": "text", "text": "Section 2.3.5", "page_idx": 2},
            {"type": "text", "text": "Appendix A", "page_idx": 2},
            {"type": "text", "text": "Figure 9.2", "page_idx": 2},
        ]
    )

    assert all(is_margin_note(block) for block in leaked)


def test_prose_mentioning_a_section_is_not_a_margin_note() -> None:
    prose = parse_blocks(
        [
            {
                "type": "text",
                "text": "As shown in Section 9.2, the bound is tight.",
                "page_idx": 0,
            },
            {
                "type": "text",
                "text": "Section 9.2 covers mixtures of Gaussians " "in detail.",
                "page_idx": 0,
            },
        ]
    )

    assert not any(is_margin_note(block) for block in prose)


def test_a_heading_that_looks_like_a_cross_reference_survives() -> None:
    heading = parse_blocks(
        [{"type": "text", "text": "Appendix A", "text_level": 2, "page_idx": 0}]
    )

    assert not is_margin_note(heading[0])
    assert "Appendix A" in assemble(heading)


def test_leaked_margin_notes_are_dropped_from_the_markdown() -> None:
    records = [
        {"type": "text", "text": "Body text.", "page_idx": 0},
        {"type": "text", "text": "Exercise 9.1", "page_idx": 0},
    ]

    out = assemble(parse_blocks(records))

    assert "Body text." in out
    assert "Exercise 9.1" not in out


# --- headings mineru misses entirely ----------------------------------------


def test_a_chapter_title_missing_from_the_blocks_is_injected() -> None:
    """mineru never emits chapter titles; the outline supplies them."""
    outline = Outline([OutlineEntry(title="9. Mixture Models and EM", depth=1, page=0)])
    records = [{"type": "text", "text": "Opening paragraph.", "page_idx": 0}]

    out = assemble(parse_blocks(records), outline=outline)

    assert "# 9. Mixture Models and EM" in out
    assert out.index("# 9. Mixture Models") < out.index("Opening paragraph.")


def test_a_heading_mineru_did_emit_is_not_duplicated() -> None:
    outline = Outline([OutlineEntry(title="9.1. K-means Clustering", depth=2, page=0)])
    records = [
        {
            "type": "text",
            "text": "9.1. K-means Clustering",
            "text_level": 2,
            "page_idx": 0,
        }
    ]

    out = assemble(parse_blocks(records), outline=outline)

    assert out.count("K-means Clustering") == 1


def test_injection_only_happens_on_the_outlines_own_page() -> None:
    outline = Outline([OutlineEntry(title="Later Chapter", depth=1, page=5)])
    records = [{"type": "text", "text": "Body.", "page_idx": 0}]

    assert "Later Chapter" not in assemble(parse_blocks(records), outline=outline)


# --- tables (carried in table_body, not text) -------------------------------


SIMPLE_TABLE = (
    "<table><tr><td>User ID</td><td>Gender</td></tr>"
    "<tr><td>2</td><td>F</td></tr></table>"
)


def test_a_table_block_is_rendered_not_dropped() -> None:
    """table blocks have no `text` at all, so falling through loses them."""
    blocks = parse_blocks(
        [{"type": "table", "table_body": SIMPLE_TABLE, "page_idx": 0}]
    )

    out = assemble(blocks)

    assert "| User ID | Gender |" in out
    assert "| 2 | F |" in out


def test_a_table_keeps_its_caption() -> None:
    blocks = parse_blocks(
        [
            {
                "type": "table",
                "table_body": SIMPLE_TABLE,
                "table_caption": ["Table 3: Users"],
                "page_idx": 0,
            }
        ]
    )

    out = assemble(blocks)

    assert "Table 3: Users" in out


def test_merged_cells_stay_as_html_rather_than_being_mangled() -> None:
    merged = '<table><tr><td colspan="2">Wide</td></tr></table>'

    assert html_table_to_markdown(merged) == merged


def test_single_span_attributes_still_convert() -> None:
    """mineru writes rowspan=1 colspan=1 on ordinary cells."""
    html = (
        '<table><tr><td rowspan="1" colspan="1">A</td>'
        '<td rowspan="1" colspan="1">B</td></tr></table>'
    )

    assert html_table_to_markdown(html) == "| A | B |\n|---|---|"


def test_ragged_rows_are_padded() -> None:
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"

    assert html_table_to_markdown(html).splitlines()[-1] == "| c |  |"


def test_unparseable_table_html_is_passed_through() -> None:
    assert html_table_to_markdown("not a table") == "not a table"


# --- which blocks own an image ----------------------------------------------


def test_only_images_and_charts_count_as_figures() -> None:
    blocks = parse_blocks(
        [
            {"type": "image", "img_path": "a.jpg", "page_idx": 0},
            {"type": "chart", "img_path": "b.jpg", "page_idx": 0},
            {"type": "equation", "img_path": "c.jpg", "text": "$$x$$", "page_idx": 0},
            {
                "type": "table",
                "img_path": "d.jpg",
                "table_body": "<table></table>",
                "page_idx": 0,
            },
        ]
    )

    assert [b.is_figure for b in blocks] == [True, True, False, False]
