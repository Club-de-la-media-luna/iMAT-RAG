# M2 — extraction benchmark

Which tool converts the corpus to Markdown, decided by measurement rather than
reputation. Reproduce with `scripts/bench_extraction.py`; raw output lives in
the knowledge base under `derived/bench/`.

## Method

Three slices, one per extraction tier, chosen before any tool was run:

| Slice | Source | Pages | Why |
| --- | --- | ---: | --- |
| `bishop-ch9` | Bishop, *PRML*, pp. 443–480 | 38 | Born-digital mathematics. Display equations, figures, algorithm boxes and numbered cross-references in one chapter. |
| `evans-scan` | Evans, *PDE*, pp. 266–315 | 50 | No text layer at all, ~24 images per page. Theorem-proof mathematics only OCR can reach. |
| `burkov-prose` | Burkov, *ML Engineering*, pp. 119–168 | 50 | Ordinary technical prose. The tier where an expensive tool should not be needed. |

Each tool runs in its own `uvx` environment — they pull conflicting torch
builds — and one at a time, because concurrent GPU work would corrupt both the
timing and the VRAM figures. Peak VRAM is sampled from `nvidia-smi` at 4 Hz
while the tool runs. Hardware: RTX 3050 Laptop, **4096 MiB VRAM**.

Flags are set to make the comparison fair on 4 GB and to enable what the design
requires, not to flatter each tool:

- `docling --enrich-formula` — off by default; without it equations degrade to
  prose.
- `marker --paginate_output` — emits the page markers citations depend on.
- `mineru -b pipeline` — instead of the default `hybrid-engine`, which loads a
  local VLM that does not fit in 4 GB.

The recorded counts are presence checks, not quality judgements. Every verdict
below also rests on reading the Markdown.

## Results

### docling 2.118.0

| slice | s/page | peak VRAM | chars | headings | display math | inline math | figures | page markers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--: |
| bishop-ch9 | 19.1 | 2723 MB | 126,800 | 26 | 87 | 18 | 15 | ✗ |
| evans-scan | 15.0 | **3887 MB** | 111,264 | 35 | 323 | 3 | 0 | ✗ |
| burkov-prose | **2.3** | 3087 MB | 107,088 | 78 | 27 | 0 | 11 | ✗ |

Projected over the basic tier: maths 9,577 pp ≈ 50.9 h, scans 979 pp ≈ 4.1 h,
prose 1,434 pp ≈ 0.9 h — **≈ 56 hours**.

**Display mathematics is genuinely good, including from scans.** Evans's trace
theorem came out of a page image with no text layer as correct LaTeX:

```latex
$$\begin{cases} u \in W^{1,p}(\mathbb{R}_+^n), & u \text{ has compact support in } \bar{\mathbb{R}}_+^n, \\
& Tu = 0 \text{ on } \partial\mathbb{R}_+^n = \mathbb{R}^{n-1}.\end{cases}$$
```

That matters: the 979 scanned pages of the basic tier are recoverable rather
than a write-off.

**Defects, in descending order of harm:**

1. **Margin notes are spliced into the middle of sentences.** Bishop's marginal
   cross-references land inline — "…we introduce the latent variable
   `Section 9.2` `Section 9.3` `Section 9.4` view of mixture distributions…" —
   cutting a sentence in half. This damages chunk boundaries and embeddings
   directly, and it is not a rare event.
2. **Inline mathematics is lost everywhere.** It degrades to flattened unicode:
   `r nk ∈ { 0 , 1 }`, `‖ x n -µ k ‖ 2`, `Tu = 0 on Rn-1`. Only display
   equations become LaTeX. The inline-math counts above are near zero for this
   reason, not because the sources lack inline maths.
3. **No page markers.** Docling keeps page provenance in its JSON export but
   drops it in Markdown, so the citation requirement cannot be met from `--to md`
   output. If docling is used, the pipeline must consume `--to json` and build
   the Markdown itself.
4. **Structure is unreliable.** `## 3. Next let ζ ∈ C∞(R) satisfy` is a numbered
   proof step promoted to a section heading — structure-aware chunking would
   split mid-proof there.
5. **Prose absorbed into equations.** PRML eq. 9.1 ends
   `\\ \text{the sum of the squares of the distances of each data point to its}$$`,
   with the same phrase repeated outside it.
6. **Invalid LaTeX emitted.** One Evans equation carries bare `&` and `\\`
   alignment markers inside plain `$$…$$` with no `aligned` environment.
7. **Absolute image paths** (`/home/javier/...`) — not portable to another
   machine.
8. **No figures extracted from the scan** (0 files). Figures inside scanned
   books are lost.
9. Ligature damage: "Webegin", "fi xed", and `&gt;` entity leakage.

**Verdict:** strong display maths, weak everything else, and too slow for the
maths tier at ~51 hours. Prose at 2.3 s/page is genuinely cheap, but PyMuPDF
already covers that tier for near-free.

### marker 2.0.0 — cannot run on this machine

All three slices failed in 9–15 s, before touching the GPU:

```
SpawnError: docker run failed:
The command 'docker' could not be found in this WSL 2 distro.
```

marker 2.0 rebuilt extraction around a vision-language model. Its `surya`
dependency now requires an LLM inference server rather than plain torch
weights, and `_autodetect_backend()` picks one by hardware: an NVIDIA GPU
selects the **vllm** backend, which it starts with `docker run`. Docker
Desktop's WSL integration is off here, so the spawn fails immediately.

Enabling Docker would not fix the underlying problem — vLLM will not serve a
VLM inside 4 GB alongside anything else. The only other backend is
**llamacpp**, which needs a `llama-server` binary (not installed, not
auto-installed) plus a GGUF download, and would make marker a VLM-based
extractor with a cost profile closer to a local model than to a converter.

**marker-pdf 1.10.2** is therefore the marker candidate: it predates the VLM
rewrite and uses dedicated layout, OCR and equation models under plain torch —
no server, no Docker. Benchmarked separately as `marker1` rather than silently
substituted, so the 2.0 blocker stays on the record.

### mineru 3.4.4

First attempt failed on all three slices in ~6 s with
`ModuleNotFoundError: No module named 'torch'`. The base distribution ships
without torch; the `pipeline` extra carries torch and torchvision. The failure
mode is unhelpful — the CLI starts, spins up its local FastAPI service, accepts
the job and only then fails inside the worker, reporting a task failure rather
than a missing dependency.

With `mineru[pipeline]` plus `six`, all three slices succeeded.

| slice | s/page | peak VRAM | chars | headings | display math | inline math | figures | page markers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--: |
| bishop-ch9 | **3.5** | 1631 MB | 110,422 | 14 | 86 | 428 | 116 | ✗ (md) |
| evans-scan | **2.1** | 1655 MB | 120,040 | 31 | 305 | 743 | 305 | ✗ (md) |
| burkov-prose | **1.0** | 1775 MB | 109,456 | 78 | 27 | 114 | 49 | ✗ (md) |

Projected over the basic tier: **≈ 12 hours**, at under half docling's VRAM.

**Inline mathematics survives**, which is where docling failed outright:

```latex
$r_{nk} \in \{0,1\}$ … $r_{nj} = 0$ for $j \neq k$
$$J = \sum_{n=1}^{N}\sum_{k=1}^{K} r_{nk}\|\mathbf{x}_n - \pmb{\mu}_k\|^2 \tag{9.1}$$
```

Note `\neq`: docling rendered the same relation as `j = k`, inverting it. Equation
numbers are emitted as real `\tag{9.1}` rather than trailing text.

**The Markdown is not the interesting output.** `<name>_content_list.json` carries
one record per block, and it is richer than any tool's Markdown:

- `page_idx` on **every** block (465 of 465 on bishop-ch9, covering pages 0–37).
  Page provenance is therefore *per block*, not per page break — a chunk's page
  range is exact rather than inferred from where a separator fell.
- `type` — `text`, `equation`, `image`, `chart`, `header`, `page_number`,
  `aside_text`. Block counts on bishop-ch9: text 239, equation 86, header 36,
  `aside_text` 36, page_number 37, image 10, chart 20.
- `text_level` — heading depth.
- `bbox` — position on the page.

Three of those directly solve defects the other tools introduce:

1. **`aside_text` isolates the margin notes.** On bishop-ch9 it captures exactly
   `'Section 9.2'`, `'Section 9.3'`, `'Exercise 9.1'` — the strings that docling
   and marker1 splice into the middle of sentences. The pipeline drops them.
2. **`page_number` and `header` separate the running furniture**, so folios and
   running heads never enter a chunk.
3. **`equation` is a block type**, so "never split inside an equation" is a
   structural fact rather than a regex guess.

Its 14 headings on bishop-ch9 are **precision, not loss**: they are exactly
Bishop's real sections (9.1, 9.1.1, 9.2, 9.2.1, 9.2.2, 9.3, 9.3.1–9.3.4, 9.4,
Exercises). docling's 26 and marker1's 30 include false positives such as
docling's `## 3. Next let ζ ∈ C∞(R) satisfy`, a numbered proof step.

### marker-pdf 1.10.2 — best output, unusable throughput

| slice | s/page | peak VRAM | chars | headings | display math | inline math | figures | page markers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--: |
| bishop-ch9 | **185.1** | **3951 MB** | 102,274 | 30 | 93 | 485 | 15 | **✓** |

Quality is the best of the three. It is the only tool that emits page markers in
Markdown (`{0}------…`), inline maths is clean LaTeX, image paths are relative,
and there is no ligature damage.

It is also **53× slower than mineru** for a marginal gain (93 vs 86 display
equations, 485 vs 428 inline). At 185 s/page the 9,577-page maths tier would
take **≈ 490 hours — 20 days**. Peak VRAM was 3951 MB of 4096, so it is
thrashing against the ceiling rather than computing; the number reflects this
GPU, not the tool in general.

The remaining two slices were not run. At ~2.6 h each they could not have
changed a decision already settled on throughput.

## Decision

**mineru 3.4.4, `-b pipeline`, consuming `content_list.json` rather than the
Markdown.** PyMuPDF still handles the prose tier, where mineru's 1.0 s/page buys
nothing over a near-instant text-layer read.

Why not the others:

- **marker 1.10.2** produces the best Markdown but at 185 s/page and 96% VRAM.
  Reconsider if the hardware changes; the quality gap is real but small.
- **marker 2.0** cannot run here at all (VLM → vLLM → Docker; and vLLM will not
  fit 4 GB).
- **docling** is 5× slower than mineru, uses more VRAM, loses inline mathematics
  entirely, inverts at least one relation (`\neq` → `=`), and emits no page
  provenance in Markdown. Its display-maths OCR is genuinely good, but mineru
  matches it (305 vs 323 display equations on the scan) while also extracting
  305 figures where docling extracted none.

Consequences for M3:

- The extract stage reads `content_list.json`, not `.md`. Page anchors come from
  `page_idx` directly, so the `<!--page:N-->` markers in the design are emitted
  by our own writer rather than scraped from a tool's output.
- `aside_text`, `page_number` and `header` blocks are dropped at extract time.
- `equation` blocks give chunking hard boundaries for free.
- Budget ≈ 12 hours for the basic tier, one machine, resumable.

### Heading depth must be reconstructed

mineru's headings are accurate but **flat**, and the chunker cannot rely on them
for the breadcrumb hierarchy:

- `text_level` takes exactly one value across the whole chapter: `2`. `9.1.
  K-means Clustering` and `9.1.1 Image segmentation and compression` are both
  level 2, so section and subsection are indistinguishable.
- The chapter title itself, `9. Mixture Models and EM`, is not captured as a
  heading at all.

Both are recoverable without re-extracting, from two sources already available:

1. **The PDF outline.** 27 of the 41 acquired books have one — Bishop's has 285
   entries with real depth (`L1 9. Mixture Models and EM`, `L2 9.1. K-means
   Clustering`). Read it with PyMuPDF and map headings onto it by page and title.
2. **The numbering in the heading text.** `9.1.1` is depth 3 by inspection. This
   covers the 14 books with no outline.

So M3 needs a heading-depth pass that combines mineru's heading detection (which
is precise) with outline or numbering data (which carries the depth). Neither
input requires another 12-hour extraction run.
