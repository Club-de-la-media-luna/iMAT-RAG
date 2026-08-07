from __future__ import annotations

import json
from pathlib import Path

from imat_rag.config import Paths
from imat_rag.ingest.assemble import Block
from imat_rag.ingest.catalogue import Book, SourceTier
from imat_rag.ingest.extract import (
    ExtractConfig,
    already_done,
    blocks_dir,
    cached_blocks,
    copy_figures,
    find_output,
    mineru_argv,
    stage_key,
)


def a_book(**overrides: object) -> Book:
    fields: dict[str, object] = {
        "slug": "murphy-vol-1",
        "path": Path("/kb/courses/IAP/raw/literature/murphy-vol-1.pdf"),
        "courses": ("IAP", "MGP"),
        "titles": ("Murphy, K. P. — Probabilistic ML",),
        "tier": SourceTier.BASIC_BOOK,
        "sha256": "a" * 64,
    }
    fields.update(overrides)
    return Book(**fields)  # type: ignore[arg-type]


# --- content addressing -----------------------------------------------------


def test_the_same_book_and_config_give_the_same_key() -> None:
    config = ExtractConfig()

    assert stage_key(a_book(), config) == stage_key(a_book(), config)


def test_different_source_bytes_change_the_key() -> None:
    config = ExtractConfig()

    assert stage_key(a_book(), config) != stage_key(a_book(sha256="b" * 64), config)


def test_changing_a_setting_changes_the_key() -> None:
    """A config change must invalidate the cache; timestamps would not notice."""
    book = a_book()

    assert stage_key(book, ExtractConfig()) != stage_key(
        book, ExtractConfig(min_figure_bytes=99)
    )


def test_the_key_does_not_depend_on_where_the_file_sits() -> None:
    """The same book under two courses must not extract twice."""
    config = ExtractConfig()
    elsewhere = a_book(path=Path("/kb/courses/MGP/raw/literature/murphy-vol-1.pdf"))

    assert stage_key(a_book(), config) == stage_key(elsewhere, config)


def test_the_fingerprint_is_stable_across_instances() -> None:
    assert ExtractConfig().fingerprint == ExtractConfig().fingerprint


# --- resume -----------------------------------------------------------------


def make_kb(root: Path) -> Paths:
    (root / "courses").mkdir(parents=True)
    (root / "courses" / "INDEX.md").write_text("# Índice\n")
    return Paths(kb_root=root)


def test_a_matching_stage_key_means_the_work_is_done(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    book = a_book()
    key = stage_key(book, ExtractConfig())
    (paths.extracted / "murphy-vol-1.meta.json").write_text(
        json.dumps({"stage_key": key})
    )

    assert already_done(paths, book, key) is True


def test_a_stale_stage_key_means_the_work_must_be_redone(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "murphy-vol-1.meta.json").write_text(
        json.dumps({"stage_key": "0000000000000000"})
    )

    assert already_done(paths, a_book(), "different") is False


def test_missing_metadata_means_the_work_must_be_done(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)

    assert already_done(paths, a_book(), "any") is False


def test_corrupt_metadata_is_treated_as_not_done(tmp_path: Path) -> None:
    """A truncated write from an interrupted run must not be trusted."""
    paths = make_kb(tmp_path)
    paths.extracted.mkdir(parents=True)
    (paths.extracted / "murphy-vol-1.meta.json").write_text("{not json")

    assert already_done(paths, a_book(), "any") is False


# --- invocation -------------------------------------------------------------


def test_the_command_carries_the_undeclared_dependency() -> None:
    argv = mineru_argv(Path("/in.pdf"), Path("/out"), ExtractConfig())

    assert "--with" in argv and "six" in argv
    assert argv[argv.index("--from") + 1] == "mineru[pipeline]"
    assert argv[argv.index("-b") + 1] == "pipeline"


def test_output_is_found_wherever_mineru_nested_it(tmp_path: Path) -> None:
    nested = tmp_path / "book" / "auto"
    nested.mkdir(parents=True)
    target = nested / "book_content_list.json"
    target.write_text("[]")

    assert find_output(tmp_path, "book") == target


def test_no_output_returns_none(tmp_path: Path) -> None:
    assert find_output(tmp_path, "book") is None


def test_output_is_found_when_mineru_named_it_after_the_file_not_the_slug(
    tmp_path: Path,
) -> None:
    """Staged material's slug says where it sits, which is not what it is called.

    A book's slug is its filename, so the two agreed and this never showed. A
    deck filed as `courses/DRL/raw/slides/tema-1/1-repasorl-1a.pdf` has the slug
    `drl-slides-tema-1-1-repasorl`, and mineru names its output for the file.
    """
    nested = tmp_path / "auto"
    nested.mkdir(parents=True)
    target = nested / "1-repasorl-1a_content_list.json"
    target.write_text("[]")

    assert find_output(tmp_path, "drl-slides-tema-1-1-repasorl") == target


# --- figures ----------------------------------------------------------------


def image_block(path: str, page: int) -> Block:
    return Block(type="image", page=page, img_path=path)


def test_figures_are_renamed_by_page_and_index(tmp_path: Path) -> None:
    source = tmp_path / "src" / "images"
    source.mkdir(parents=True)
    for name in ("aaa.jpg", "bbb.jpg"):
        (source / name).write_bytes(b"x" * 5000)
    blocks = [image_block("images/aaa.jpg", 7), image_block("images/bbb.jpg", 7)]

    names = copy_figures(tmp_path / "src", tmp_path / "out", blocks, ExtractConfig())

    assert names == {
        "images/aaa.jpg": "p0007-fig1.jpg",
        "images/bbb.jpg": "p0007-fig2.jpg",
    }
    assert (tmp_path / "out" / "p0007-fig1.jpg").is_file()


def test_tiny_figures_are_dropped(tmp_path: Path) -> None:
    """mineru extracts every region; decorative fragments are not content."""
    source = tmp_path / "src" / "images"
    source.mkdir(parents=True)
    (source / "tiny.jpg").write_bytes(b"x" * 10)
    blocks = [image_block("images/tiny.jpg", 1)]

    names = copy_figures(tmp_path / "src", tmp_path / "out", blocks, ExtractConfig())

    assert names == {}
    assert list((tmp_path / "out").iterdir()) == []


def test_a_repeated_figure_is_copied_once(tmp_path: Path) -> None:
    source = tmp_path / "src" / "images"
    source.mkdir(parents=True)
    (source / "a.jpg").write_bytes(b"x" * 5000)
    blocks = [image_block("images/a.jpg", 1), image_block("images/a.jpg", 1)]

    names = copy_figures(tmp_path / "src", tmp_path / "out", blocks, ExtractConfig())

    assert len(names) == 1
    assert len(list((tmp_path / "out").iterdir())) == 1


def test_a_missing_figure_file_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    blocks = [image_block("images/gone.jpg", 1)]

    assert (
        copy_figures(tmp_path / "src", tmp_path / "out", blocks, ExtractConfig()) == {}
    )


def test_page_numbers_are_zero_padded_so_names_sort(tmp_path: Path) -> None:
    source = tmp_path / "src" / "images"
    source.mkdir(parents=True)
    for name in ("a.jpg", "b.jpg"):
        (source / name).write_bytes(b"x" * 5000)
    blocks = [image_block("images/a.jpg", 9), image_block("images/b.jpg", 100)]

    names = copy_figures(tmp_path / "src", tmp_path / "out", blocks, ExtractConfig())

    assert sorted(names.values()) == ["p0009-fig1.jpg", "p0100-fig1.jpg"]


# --- caching mineru's own output --------------------------------------------


def test_cached_blocks_are_reused_when_the_key_matches(tmp_path: Path) -> None:
    """Assembly must never force a book back through the GPU."""
    paths = make_kb(tmp_path)
    directory = blocks_dir(paths, "murphy-vol-1")
    (directory).mkdir(parents=True)
    (directory / "content_list.json").write_text("[]")
    (directory / "stage_key").write_text("abc123")

    assert cached_blocks(paths, a_book(), "abc123") == directory / "content_list.json"


def test_cached_blocks_are_rejected_when_the_key_differs(tmp_path: Path) -> None:
    paths = make_kb(tmp_path)
    directory = blocks_dir(paths, "murphy-vol-1")
    directory.mkdir(parents=True)
    (directory / "content_list.json").write_text("[]")
    (directory / "stage_key").write_text("old")

    assert cached_blocks(paths, a_book(), "new") is None


def test_a_content_list_with_no_stamp_is_not_trusted(tmp_path: Path) -> None:
    """An interrupted run can leave the file without its key."""
    paths = make_kb(tmp_path)
    directory = blocks_dir(paths, "murphy-vol-1")
    directory.mkdir(parents=True)
    (directory / "content_list.json").write_text("[]")

    assert cached_blocks(paths, a_book(), "abc123") is None


def test_figures_resolve_against_the_cached_images_directory(tmp_path: Path) -> None:
    """Cached blocks flatten mineru's images/ layout; lookup must follow."""
    cache = tmp_path / "blocks"
    (cache / "images").mkdir(parents=True)
    (cache / "images" / "a.jpg").write_bytes(b"x" * 5000)
    blocks = [Block(type="image", page=3, img_path="images/a.jpg")]

    names = copy_figures(cache, tmp_path / "out", blocks, ExtractConfig())

    assert names == {"images/a.jpg": "p0003-fig1.jpg"}
