#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf", "typer"]
# ///
"""Compare PDF-to-Markdown tools on representative slices of the corpus (M2).

The corpus is not uniform: most of it is born-digital mathematics, a fifth of
the basic tier is scanned, and a chunk of it is ordinary technical prose. A
tool that handles one well may be useless on another, so this measures each
tool against one slice of each kind rather than against an average.

    uv run scripts/bench_extraction.py samples          # cut the slices
    uv run scripts/bench_extraction.py run --tool NAME  # convert them
    uv run scripts/bench_extraction.py report           # compare

Slices and outputs are written under the knowledge base's `derived/bench/`,
never into this repository, which holds no data.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import fitz
import typer

app = typer.Typer(help=__doc__, no_args_is_help=True)


# --- what gets measured -----------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One slice of one book, chosen to represent an extraction tier."""

    name: str
    tier: str
    course: str
    pdf: str
    first_page: int  # 1-based, inclusive, as shown by a PDF reader
    last_page: int
    why: str


SAMPLES = (
    Sample(
        name="bishop-ch9",
        tier="maths",
        course="IAP",
        pdf="bishop-c-m-pattern-recognition-and-machine-learning-2006.pdf",
        first_page=443,
        last_page=480,
        why="Ch. 9 Mixture Models and EM: display equations, figures, "
        "algorithm boxes and numbered cross-references in one chapter.",
    ),
    Sample(
        name="evans-scan",
        tier="scan",
        course="MD",
        pdf="evans-l-c-partial-differential-equations.pdf",
        first_page=266,
        last_page=315,
        why="No text layer at all, ~24 images per page. The hardest case: "
        "theorem-proof mathematics that only OCR can reach.",
    ),
    Sample(
        name="burkov-prose",
        tier="prose",
        course="IM",
        pdf="burkov-a-machine-learning-engineering-2020.pdf",
        first_page=119,
        last_page=168,
        why="Ordinary technical prose with occasional figures. The tier where "
        "an expensive tool should not be needed.",
    ),
)


# --- locating things --------------------------------------------------------


def kb_root() -> Path:
    """Resolve the knowledge base the same way the package does."""
    import os

    from_env = os.environ.get("MASTER_KB_PATH")
    marker = Path("courses") / "INDEX.md"
    if from_env:
        candidate = Path(from_env).expanduser()
        if not (candidate / marker).is_file():
            raise typer.BadParameter(
                f"MASTER_KB_PATH={from_env} is not a knowledge base"
            )
        return candidate.resolve()
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        if (directory / "master_kb" / marker).is_file():
            return (directory / "master_kb").resolve()
    raise typer.BadParameter("No knowledge base found; set MASTER_KB_PATH")


def bench_dir() -> Path:
    return kb_root() / "derived" / "bench"


def source_pdf(sample: Sample) -> Path:
    return kb_root() / "courses" / sample.course / "raw" / "literature" / sample.pdf


# --- peak VRAM --------------------------------------------------------------


class VramPoller:
    """Sample used GPU memory while something else runs.

    Polls `nvidia-smi` rather than reading torch counters, because each tool
    runs in its own subprocess and its own environment.
    """

    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self.peak_mb = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                self.peak_mb = max(self.peak_mb, int(out.stdout.strip().split("\n")[0]))
            except (subprocess.SubprocessError, ValueError, FileNotFoundError):
                pass
            self._stop.wait(self.interval)

    def __enter__(self) -> VramPoller:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


# --- what "good output" means -----------------------------------------------


def score(markdown: str, out_dir: Path) -> dict[str, int | bool]:
    """Count the features the pipeline depends on downstream.

    These are not quality judgements — they are presence checks for the things
    the design requires: LaTeX for equations, a heading tree for structure-aware
    chunking, page markers for citations, and extracted figures.
    """
    import re

    display = len(re.findall(r"\$\$.+?\$\$", markdown, re.S))
    display += len(re.findall(r"\\\[.+?\\\]", markdown, re.S))
    display += len(re.findall(r"\\begin\{(equation|align|gather)", markdown))
    inline = len(re.findall(r"(?<!\$)\$[^$\n]+\$(?!\$)", markdown))
    inline += len(re.findall(r"\\\(.+?\\\)", markdown))

    return {
        "chars": len(markdown),
        "headings": len(re.findall(r"^#{1,6} ", markdown, re.M)),
        "display_math": display,
        "inline_math": inline,
        "tables": len(re.findall(r"^\|.+\|$", markdown, re.M)),
        "code_blocks": markdown.count("```") // 2,
        "image_refs": len(re.findall(r"!\[[^\]]*\]\(", markdown)),
        "image_files": len(
            [
                p
                for p in out_dir.rglob("*")
                if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
            ]
        ),
        "has_page_markers": bool(
            re.search(r"(?i)<!--\s*page|\{\d+\}-{10,}|page[_ -]?\d+\s*-->", markdown)
        ),
    }


# --- tool invocations -------------------------------------------------------

TOOLS: dict[str, list[str]] = {
    # argv templates using the placeholders {pdf} and {out}. Each tool runs in
    # its own uvx environment: they pull conflicting torch builds and must not
    # share one.
    #
    # Flags are chosen to make the comparison fair on a 4 GB GPU and to enable
    # the features the design depends on, rather than to show each tool at its
    # best:
    #   docling  --enrich-formula turns on formula understanding, which is off
    #            by default and without which equations come out as prose.
    #   marker   --paginate_output emits the page markers citations need.
    #   mineru   -b pipeline instead of the default hybrid-engine, which loads
    #            a local VLM that does not fit in 4 GB.
    "docling": [
        "uvx",
        "--from",
        "docling",
        "docling",
        "convert",
        "{pdf}",
        "--to",
        "md",
        "--output",
        "{out}",
        "--enrich-formula",
        "--image-export-mode",
        "referenced",
    ],
    # marker 2.0 rebuilt extraction around a VLM and needs an inference server:
    # surya autodetects an NVIDIA GPU, selects the vllm backend, and spawns it
    # via `docker run`. Kept here to document that it does not run on this
    # machine — Docker Desktop's WSL integration is off, and vLLM would not fit
    # in 4 GB regardless. The llamacpp fallback needs a llama-server binary and
    # a GGUF download.
    "marker": [
        "uvx",
        "--from",
        "marker-pdf",
        "marker_single",
        "{pdf}",
        "--output_dir",
        "{out}",
        "--output_format",
        "markdown",
        "--paginate_output",
    ],
    # marker 1.x predates that change: dedicated layout, OCR and equation
    # models under plain torch, no server, no Docker. The version that can
    # actually run on 4 GB.
    "marker1": [
        "uvx",
        "--from",
        "marker-pdf==1.10.2",
        "marker_single",
        "{pdf}",
        "--output_dir",
        "{out}",
        "--output_format",
        "markdown",
        "--paginate_output",
    ],
    # Two packaging problems, both upstream:
    #   1. The base distribution ships without torch; the `pipeline` extra
    #      carries torch and torchvision.
    #   2. Even with it, mineru 3.4.4's vendored pytorchocr imports `six`
    #      without declaring it. An AST scan of the package confirms `six` is
    #      the only genuinely undeclared dependency — every other unresolved
    #      import (boto3, gradio, vllm, lmdeploy, mlx_vlm, flash_attn,
    #      torch_npu) belongs to an optional backend that is guarded.
    # Both surface as a task failure from mineru's own local API service rather
    # than as an install error, which makes them slow to diagnose.
    "mineru": [
        "uvx",
        "--from",
        "mineru[pipeline]",
        "--with",
        "six",
        "mineru",
        "-p",
        "{pdf}",
        "-o",
        "{out}",
        "-b",
        "pipeline",
        "-m",
        "auto",
    ],
}


def newest_markdown(out_dir: Path) -> str:
    """Tools disagree about where they put the .md; take the largest one."""
    candidates = sorted(
        out_dir.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True
    )
    return (
        candidates[0].read_text(encoding="utf-8", errors="replace")
        if candidates
        else ""
    )


# --- commands ---------------------------------------------------------------


@app.command()
def samples() -> None:
    """Cut the benchmark slices out of the source PDFs."""
    target = bench_dir() / "samples"
    target.mkdir(parents=True, exist_ok=True)

    for sample in SAMPLES:
        src = source_pdf(sample)
        if not src.is_file():
            typer.secho(f"missing: {src}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        doc = fitz.open(src)
        sliced = fitz.open()
        sliced.insert_pdf(
            doc, from_page=sample.first_page - 1, to_page=sample.last_page - 1
        )
        out = target / f"{sample.name}.pdf"
        sliced.save(out)
        pages = len(sliced)
        chars = sum(len(sliced[i].get_text("text")) for i in range(pages))
        sliced.close()
        doc.close()

        typer.echo(
            f"{sample.name:<14} {sample.tier:<6} {pages:>3} pages  "
            f"{chars:>7} chars  {out.stat().st_size / 1024:>7.0f} KB"
        )

    (target / "SAMPLES.json").write_text(
        json.dumps([s.__dict__ for s in SAMPLES], indent=2, ensure_ascii=False)
    )


@app.command()
def run(
    tool: str = typer.Option(..., help=f"One of: {', '.join(TOOLS)}"),
    timeout: int = typer.Option(3600, help="Per-sample timeout in seconds"),
) -> None:
    """Convert every slice with one tool, recording time, VRAM and features."""
    if tool not in TOOLS:
        raise typer.BadParameter(
            f"unknown tool {tool!r}; expected one of {', '.join(TOOLS)}"
        )

    results_dir = bench_dir() / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    for sample in SAMPLES:
        pdf = bench_dir() / "samples" / f"{sample.name}.pdf"
        if not pdf.is_file():
            raise typer.BadParameter(f"{pdf} missing; run `samples` first")

        out_dir = bench_dir() / "out" / tool / sample.name
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)

        argv = [part.format(pdf=str(pdf), out=str(out_dir)) for part in TOOLS[tool]]
        typer.echo(f"\n{tool} / {sample.name}: {' '.join(argv)}")

        started = time.monotonic()
        timed_out = False
        stderr = ""
        returncode = 0
        with VramPoller() as vram:
            try:
                proc = subprocess.run(
                    argv, capture_output=True, text=True, timeout=timeout, check=False
                )
                returncode = proc.returncode
                stderr = proc.stderr
            except subprocess.TimeoutExpired as expired:
                # A timeout is a result, not a crash. Record it and move to the
                # next slice, or one slow tool discards the whole run.
                timed_out = True
                returncode = -1
                stderr = f"timed out after {timeout}s\n{expired.stderr or ''}"
        elapsed = time.monotonic() - started

        markdown = newest_markdown(out_dir)
        record: dict[str, object] = {
            "tool": tool,
            "sample": sample.name,
            "tier": sample.tier,
            "pages": sample.last_page - sample.first_page + 1,
            "ok": returncode == 0 and bool(markdown),
            "timed_out": timed_out,
            "returncode": returncode,
            "seconds": round(elapsed, 1),
            "seconds_per_page": round(
                elapsed / (sample.last_page - sample.first_page + 1), 2
            ),
            "peak_vram_mb": vram.peak_mb,
            "argv": argv,
            **score(markdown, out_dir),
        }
        if returncode != 0:
            record["stderr_tail"] = stderr[-2000:]

        (results_dir / f"{tool}__{sample.name}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False)
        )
        status = (
            "ok"
            if record["ok"]
            else ("TIMEOUT" if timed_out else f"FAILED rc={returncode}")
        )
        typer.echo(
            f"  {status}  {record['seconds']}s  {record['peak_vram_mb']}MB  "
            f"{record['chars']} chars  {record['display_math']} display-math  "
            f"{record['headings']} headings  page-markers={record['has_page_markers']}"
        )


@app.command()
def report() -> None:
    """Print the comparison across every tool and slice recorded so far."""
    results_dir = bench_dir() / "results"
    records = [json.loads(p.read_text()) for p in sorted(results_dir.glob("*.json"))]
    if not records:
        typer.echo("No results yet.")
        raise typer.Exit(code=1)

    header = (
        f"{'tool':<9} {'sample':<14} {'ok':<3} {'s/pg':>6} {'VRAM':>6} "
        f"{'chars':>8} {'head':>5} {'disp$':>6} {'inl$':>6} {'imgs':>5} {'pages?':>7}"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for r in sorted(records, key=lambda r: (r["tier"], r["tool"])):
        typer.echo(
            f"{r['tool']:<9} {r['sample']:<14} {'y' if r['ok'] else 'N':<3} "
            f"{r['seconds_per_page']:>6} {r['peak_vram_mb']:>6} {r['chars']:>8} "
            f"{r['headings']:>5} {r['display_math']:>6} {r['inline_math']:>6} "
            f"{r['image_files']:>5} {str(r['has_page_markers']):>7}"
        )


if __name__ == "__main__":
    app()
