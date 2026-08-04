"""Run mineru over a book and write the artifacts the pipeline consumes.

The stage is content-addressed: a book's output is keyed by the hash of its
source bytes and the extraction settings, so re-running skips work already
done and changing a setting invalidates exactly what that setting affects.
Extraction of the basic tier is roughly twelve hours and will be interrupted;
resuming has to cost nothing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import statistics
import subprocess
from collections.abc import Sequence
from pathlib import Path

import fitz
from pydantic import BaseModel, Field

from imat_rag.config import Paths
from imat_rag.ingest.assemble import (
    Block,
    Outline,
    OutlineEntry,
    assemble,
    page_span,
    parse_blocks,
)
from imat_rag.ingest.catalogue import Book, sha256_of

SCAN_CHARS_PER_PAGE = 200
"""Below this median, a page has no usable text layer and the book is a scan."""

PROBE_FRACTIONS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
"""Where to sample when probing, avoiding front and back matter."""


class ExtractConfig(BaseModel, frozen=True):
    """Everything that changes the output, and therefore the content address."""

    tool: str = "mineru"
    tool_spec: str = "mineru[pipeline]"
    extra_packages: tuple[str, ...] = ("six",)
    backend: str = "pipeline"
    method: str = "auto"
    min_figure_bytes: int = 3072
    """Figures smaller than this are decorative fragments, not content.

    mineru extracts every figure region it finds — 116 from 38 pages of Bishop —
    so the basic tier lands near 40,000 files. Dropping the tiny ones keeps the
    count manageable without losing diagrams.
    """

    @property
    def fingerprint(self) -> str:
        """Stable hash of the settings, for the stage key."""
        payload = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]


class BookMeta(BaseModel):
    """The sidecar written beside each book's Markdown."""

    slug: str
    courses: tuple[str, ...]
    titles: tuple[str, ...]
    tier: int
    extraction_tier: str
    pages: int
    page_span: tuple[int, int]
    source_sha256: str
    source_path: str
    stage_key: str
    tool: str
    figures: int
    chars: int
    warnings: list[str] = Field(default_factory=list)


def stage_key(book: Book, config: ExtractConfig) -> str:
    """Content address for one book under one configuration."""
    return hashlib.sha256(f"{book.sha256}:{config.fingerprint}".encode()).hexdigest()[
        :16
    ]


def probe(path: Path) -> tuple[int, str, list[OutlineEntry], list[str]]:
    """Page count, extraction tier, outline and any warnings for a source PDF."""
    warnings: list[str] = []
    with fitz.open(path) as doc:
        pages = len(doc)
        samples = [int(pages * f) for f in PROBE_FRACTIONS if int(pages * f) < pages]
        lengths = [len(doc[i].get_text("text").strip()) for i in samples]
        median = statistics.median(lengths) if lengths else 0
        outline = [
            OutlineEntry(title=title.strip(), depth=depth, page=max(page - 1, 0))
            for depth, title, page in doc.get_toc()
        ]

    tier = "scan" if median < SCAN_CHARS_PER_PAGE else "born_digital"
    if tier == "scan":
        warnings.append("no text layer; depends entirely on OCR")
    if not outline:
        warnings.append("no PDF outline; heading depth comes from numbering alone")
    if pages < 20:
        warnings.append(f"only {pages} pages; source may be a truncated download")
    return pages, tier, outline, warnings


def describe(book: Book) -> Book:
    """Fill in the fields that require opening the PDF."""
    pages, tier, _, warnings = probe(book.path)
    return book.model_copy(
        update={
            "pages": pages,
            "sha256": sha256_of(book.path),
            "extraction_tier": tier,
            "warnings": tuple(warnings),
        }
    )


def mineru_argv(pdf: Path, out_dir: Path, config: ExtractConfig) -> list[str]:
    """Command line for one book.

    mineru runs in its own uvx environment: the base distribution ships without
    torch, and its vendored pytorchocr imports `six` without declaring it.
    """
    argv = ["uvx", "--from", config.tool_spec]
    for package in config.extra_packages:
        argv += ["--with", package]
    return argv + [
        config.tool,
        "-p",
        str(pdf),
        "-o",
        str(out_dir),
        "-b",
        config.backend,
        "-m",
        config.method,
    ]


def find_output(work_dir: Path, slug: str) -> Path | None:
    """Locate mineru's content_list.json, wherever it nested it."""
    matches = sorted(work_dir.rglob(f"{slug}_content_list.json"))
    return matches[0] if matches else None


def copy_figures(
    source_dir: Path,
    target_dir: Path,
    blocks: Sequence[Block],
    config: ExtractConfig,
) -> dict[str, str]:
    """Copy figures worth keeping, returning a map from mineru's path to ours.

    Names encode the page, so a figure reference in the Markdown is already a
    citation.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    names: dict[str, str] = {}
    per_page: dict[int, int] = {}

    for block in blocks:
        # Equation and table blocks carry an img_path too, but their content is
        # already LaTeX and HTML. Copying those pictures duplicated content and
        # produced three images for every one worth keeping.
        if not block.is_figure or block.img_path in names:
            continue
        origin = source_dir / block.img_path
        if not origin.is_file():
            origin = source_dir / "images" / Path(block.img_path).name
        if not origin.is_file() or origin.stat().st_size < config.min_figure_bytes:
            continue
        index = per_page.get(block.page, 0) + 1
        per_page[block.page] = index
        name = f"p{block.page:04d}-fig{index}{origin.suffix}"
        shutil.copy2(origin, target_dir / name)
        names[block.img_path] = name

    return names


def blocks_dir(paths: Paths, slug: str) -> Path:
    """Where mineru's own output is cached for a book."""
    return paths.derived / "blocks" / slug


def cached_blocks(paths: Paths, book: Book, key: str) -> Path | None:
    """The cached content list for this exact book and configuration, if any.

    Caching mineru's output rather than only the Markdown is what makes the
    stage genuinely cheap to iterate on: assembly is milliseconds, extraction
    is minutes to hours. A change to how Markdown is assembled must not force
    a book back through the GPU.
    """
    directory = blocks_dir(paths, book.slug)
    content_list = directory / "content_list.json"
    stamp = directory / "stage_key"
    if not (content_list.is_file() and stamp.is_file()):
        return None
    return content_list if stamp.read_text().strip() == key else None


def already_done(paths: Paths, book: Book, key: str) -> bool:
    """Whether this exact book and configuration has been extracted before."""
    meta_path = paths.extracted / f"{book.slug}.meta.json"
    if not meta_path.is_file():
        return False
    try:
        return bool(json.loads(meta_path.read_text()).get("stage_key") == key)
    except (json.JSONDecodeError, OSError):
        return False


def run_mineru(
    paths: Paths, book: Book, key: str, config: ExtractConfig, timeout: int
) -> Path:
    """Produce and cache mineru's content list plus the figures it references."""
    if (cached := cached_blocks(paths, book, key)) is not None:
        return cached

    work_dir = paths.derived / "work" / book.slug
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    try:
        subprocess.run(
            mineru_argv(book.path, work_dir, config),
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        produced = find_output(work_dir, book.slug)
        if produced is None:
            raise FileNotFoundError(f"mineru produced no content list for {book.slug}")

        target = blocks_dir(paths, book.slug)
        shutil.rmtree(target, ignore_errors=True)
        (target / "images").mkdir(parents=True)
        shutil.copy2(produced, target / "content_list.json")

        blocks = parse_blocks(json.loads(produced.read_text(encoding="utf-8")))
        for block in blocks:
            # Only figures are kept. Equation and table images are pictures of
            # content we already hold as LaTeX and HTML.
            origin = produced.parent / block.img_path
            if block.is_figure and origin.is_file():
                shutil.copy2(origin, target / "images" / Path(block.img_path).name)
        (target / "stage_key").write_text(key)
        return target / "content_list.json"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def extract_book(
    paths: Paths,
    book: Book,
    config: ExtractConfig | None = None,
    timeout: int = 14400,
) -> BookMeta | None:
    """Extract one book, or return None if its output is already current."""
    config = config or ExtractConfig()
    described = describe(book)
    key = stage_key(described, config)
    if already_done(paths, described, key):
        return None

    content_list = run_mineru(paths, described, key, config, timeout)
    blocks = parse_blocks(json.loads(content_list.read_text(encoding="utf-8")))
    _, _, outline_entries, _ = probe(described.path)

    figures = copy_figures(
        content_list.parent,
        paths.figures / described.slug,
        blocks,
        config,
    )
    markdown = assemble(blocks, Outline(outline_entries), figures)

    paths.extracted.mkdir(parents=True, exist_ok=True)
    (paths.extracted / f"{described.slug}.md").write_text(markdown, encoding="utf-8")

    meta = BookMeta(
        slug=described.slug,
        courses=described.courses,
        titles=described.titles,
        tier=int(described.tier),
        extraction_tier=described.extraction_tier,
        pages=described.pages,
        page_span=page_span(markdown),
        source_sha256=described.sha256,
        source_path=str(described.path),
        stage_key=key,
        tool=f"{config.tool} {config.backend}",
        figures=len(figures),
        chars=len(markdown),
        warnings=list(described.warnings),
    )
    (paths.extracted / f"{described.slug}.meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8"
    )
    return meta
