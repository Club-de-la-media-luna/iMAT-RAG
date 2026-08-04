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

Rerunning as `mineru[pipeline]`.

## Decision

Pending — recorded here once all three have run.
