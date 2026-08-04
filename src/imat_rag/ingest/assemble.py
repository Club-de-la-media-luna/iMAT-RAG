"""Turn mineru's typed blocks into the Markdown the pipeline consumes.

mineru's own Markdown is not used. `content_list.json` carries one record per
block with a type, a page index and a bounding box, and that structure is
exactly what the later stages need — see ADR-0005. Assembling the Markdown here
is what makes page anchors, margin-note removal and heading depth possible at
all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel

DISCARDED_TYPES = frozenset({"aside_text", "page_number", "header", "footer"})
"""Blocks dropped before assembly.

`aside_text` is the important one: it holds the marginal cross-references
("Section 9.2", "Exercise 9.1") that both marker and docling splice into the
middle of sentences, cutting them in half. The rest is running furniture.
"""

CROSS_REFERENCE = re.compile(
    r"^(Section|Chapter|Appendix|Exercise|Figure|Table|Sección|Capítulo|Ejercicio)"
    r"\s+[\dA-Z]+(?:\.\d+)*\.?$"
)
"""A block consisting *only* of a cross-reference is a margin note.

mineru types most of them `aside_text`, but not all: on one 38-page chapter, 35
of 44 were typed correctly, one was `footer`, and eight arrived as ordinary
`text`. Prose never consists solely of "Section 9.2", so matching the whole
block is safe — and headings are excluded separately, since they carry a
`text_level`.
"""

PAGE_ANCHOR = "<!--page:{page}-->"

# `9.1.1` is depth 3, `9.1` depth 2, `9` depth 1. Trailing dots are common
# ("9.1. K-means Clustering") and carry no depth.
NUMBERING = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)*)\.?\s+\S")

MAX_HEADING_DEPTH = 6


FIGURE_TYPES = frozenset({"image", "chart"})
"""Block types whose `img_path` is worth keeping as a file.

`equation` and `table` blocks carry an `img_path` too — a picture of the
equation or table — but their content is already available as LaTeX and HTML
respectively. Copying those images duplicates content we can already read and
would add 305 files for a single 50-page scanned sample.
"""

CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
SPANNING = re.compile(r'(?:rowspan|colspan)\s*=\s*"?([2-9]|\d{2,})', re.IGNORECASE)


class Block(BaseModel, frozen=True):
    """One record from `content_list.json`, normalised."""

    type: str
    page: int
    text: str = ""
    text_level: int | None = None
    img_path: str = ""
    caption: str = ""
    table_body: str = ""

    @property
    def is_heading(self) -> bool:
        """Whether mineru marked this block as a heading."""
        return self.text_level is not None

    @property
    def is_figure(self) -> bool:
        """Whether this block's image is content in its own right."""
        return self.type in FIGURE_TYPES and bool(self.img_path)


def html_table_to_markdown(html: str) -> str:
    """Convert mineru's HTML table to a Markdown pipe table.

    Tables with merged cells cannot be represented as a pipe table, so those
    are left as HTML — Markdown passes it through, and mangling the structure
    would be worse than keeping tags.
    """
    if SPANNING.search(html):
        return html.strip()

    rows = [
        [TAG.sub("", cell).strip() for cell in CELL.findall(row)]
        for row in ROW.findall(html)
    ]
    rows = [row for row in rows if row]
    if not rows:
        return html.strip()

    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(padded[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join(lines)


class OutlineEntry(BaseModel, frozen=True):
    """One entry of the source PDF's own table of contents.

    `page` is a zero-based index into the document being assembled, so callers
    working on a page range must offset PyMuPDF's one-based outline themselves.
    """

    title: str
    depth: int
    page: int


class Outline:
    """The source PDF's table of contents, where it has one.

    27 of the 41 acquired books carry an outline. It supplies the two things
    mineru cannot: real heading depth (its `text_level` is always 2, so `9.1`
    and `9.1.1` are indistinguishable) and headings it misses entirely —
    chapter titles among them.
    """

    def __init__(self, entries: Iterable[OutlineEntry] = ()) -> None:
        self._entries = list(entries)
        self._by_title = {entry.title.strip().lower(): entry for entry in self._entries}

    def __bool__(self) -> bool:
        return bool(self._entries)

    def depth_of(self, title: str) -> int | None:
        """The outline's depth for a heading, or None if it does not know it."""
        entry = self._by_title.get(title.strip().lower())
        return entry.depth if entry else None

    def starting_on(self, page: int) -> list[OutlineEntry]:
        """Outline entries the source places on this page."""
        return [entry for entry in self._entries if entry.page == page]


def _as_caption(value: Any) -> str:
    """mineru writes captions as a list, and sometimes as the string "[]"."""
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    text = str(value or "").strip()
    return "" if text in {"[]", "None"} else text


def parse_blocks(records: Iterable[dict[str, Any]]) -> list[Block]:
    """Normalise raw `content_list.json` records, keeping document order."""
    blocks: list[Block] = []
    for record in records:
        level = record.get("text_level")
        blocks.append(
            Block(
                type=str(record.get("type", "text")),
                page=int(record.get("page_idx", 0)),
                text=str(record.get("text", "") or ""),
                text_level=int(level) if level not in (None, "") else None,
                img_path=str(record.get("img_path", "") or ""),
                caption=_as_caption(
                    record.get("image_caption")
                    or record.get("chart_caption")
                    or record.get("table_caption")
                ),
                table_body=str(record.get("table_body", "") or ""),
            )
        )
    return blocks


def is_margin_note(block: Block) -> bool:
    """Whether a block is a marginal cross-reference rather than content."""
    if block.is_heading or block.type != "text":
        return False
    return bool(CROSS_REFERENCE.match(block.text.strip()))


def heading_depth(text: str, outline: Outline | None = None) -> int:
    """Work out how deeply a heading nests.

    The outline wins when it knows the heading; otherwise the numbering in the
    heading text carries the depth. Unnumbered headings default to section
    level, which keeps "Exercises" below a chapter without inventing structure.
    """
    stripped = text.strip()
    if outline and (depth := outline.depth_of(stripped)) is not None:
        return depth
    if match := NUMBERING.match(stripped):
        return match.group("number").count(".") + 1
    return 2


def _heading(text: str, outline: Outline | None) -> str:
    depth = min(heading_depth(text, outline), MAX_HEADING_DEPTH)
    return f"{'#' * depth} {text.strip()}"


def _render_figure(block: Block, figures: dict[str, str]) -> str:
    name = figures.get(block.img_path, block.img_path)
    return f"![{block.caption}]({name})" if name else ""


def _render_table(block: Block) -> str:
    """A table block holds HTML in `table_body` and no `text` at all."""
    table = html_table_to_markdown(block.table_body)
    if not table:
        return ""
    return f"{block.caption}\n\n{table}" if block.caption else table


def _render_text(block: Block, outline: Outline | None) -> str:
    text = block.text.strip()
    if not text or block.type == "equation":
        return text
    return _heading(text, outline) if block.is_heading else text


def _render(block: Block, outline: Outline | None, figures: dict[str, str]) -> str:
    """Render one block, or the empty string if it carries nothing."""
    if block.type in FIGURE_TYPES:
        return _render_figure(block, figures)
    if block.type == "table":
        return _render_table(block)
    return _render_text(block, outline)


def assemble(
    blocks: Sequence[Block],
    outline: Outline | None = None,
    figure_names: dict[str, str] | None = None,
) -> str:
    """Render blocks to Markdown with a page anchor at every page boundary.

    Headings the outline knows about but mineru did not emit are injected at the
    page where the outline places them — this is what recovers chapter titles,
    which mineru misses entirely.
    """
    figures = figure_names or {}
    out: list[str] = []
    current_page = -1

    for index, block in enumerate(blocks):
        if block.type in DISCARDED_TYPES or is_margin_note(block):
            continue

        if block.page != current_page:
            current_page = block.page
            out.append(PAGE_ANCHOR.format(page=block.page))
            if outline:
                out.extend(_injected_headings(blocks, index, block.page, outline))

        if rendered := _render(block, outline, figures):
            out.append(rendered)

    return "\n\n".join(out) + "\n"


def _injected_headings(
    blocks: Sequence[Block], index: int, page: int, outline: Outline
) -> list[str]:
    """Outline headings for `page` that mineru did not emit itself."""
    emitted = {
        block.text.strip().lower()
        for block in blocks[index:]
        if block.page == page and block.is_heading
    }
    return [
        _heading(entry.title, outline)
        for entry in outline.starting_on(page)
        if entry.title.strip().lower() not in emitted
    ]


def page_span(markdown: str) -> tuple[int, int]:
    """First and last page referenced by anchors, for metadata and citations."""
    pages = [int(n) for n in re.findall(r"<!--page:(\d+)-->", markdown)]
    return (min(pages), max(pages)) if pages else (0, 0)
