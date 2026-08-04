# Extraction uses mineru's `content_list.json`, not any tool's Markdown

The extract stage runs **mineru 3.4.4 with `-b pipeline`** and consumes
`<name>_content_list.json` — one typed, page-stamped record per block — rather
than the Markdown any of the candidates produce. PyMuPDF still handles the prose
tier. Measured in M2; see [the benchmark](../m2-extraction-benchmark.md).

## Considered Options

**marker-pdf 1.10.2** produced the best Markdown of the three: page markers,
clean inline LaTeX, relative image paths. It runs at **185 s/page** and peaks at
3951 MB of 4096 MB VRAM, thrashing against the ceiling — roughly **490 hours**
for the 9,577-page maths tier, against mineru's ~12 hours for the whole basic
tier. The quality gain is small (93 vs 86 display equations, 485 vs 428 inline)
and does not buy a 53× slowdown.

**marker-pdf 2.0** cannot run on this machine. It rebuilt extraction around a
vision-language model; surya now selects an inference backend by hardware, picks
vLLM on an NVIDIA GPU, and starts it with `docker run`. vLLM would not fit in
4 GB even with Docker enabled.

**docling 2.118** is 5× slower than mineru, uses more VRAM, and **loses inline
mathematics entirely** — it flattens `$r_{nk} \in \{0,1\}$` to `r nk ∈ { 0 , 1 }`
and rendered `j \neq k` as `j = k`, inverting the relation. It also splices
margin notes into the middle of sentences and emits no page provenance in
Markdown.

## Consequences

The decisive property is not speed but **structure**. `content_list.json` gives
what the design needs and no Markdown does:

- `page_idx` on every block, so a chunk's page range is exact rather than
  inferred from where a page separator landed. The `<!--page:N-->` anchors in the
  design are written by our own code from this field.
- `type` distinguishes `text`, `equation`, `image`, `chart`, `header`,
  `page_number` and `aside_text`. Dropping the last three removes running heads,
  folios and margin notes — the last being the defect that corrupts prose in both
  other tools.
- `equation` as a block type makes "never split inside an equation" structural
  rather than a regex guess.

The cost is that Markdown becomes **our** output format, not a tool's. The
extract stage assembles it from typed blocks. That is more code than reading a
`.md`, and it is the reason the stage can meet the citation requirement at all.

One gap has to be filled separately: mineru's headings are accurate but flat —
`text_level` is always `2`, so `9.1` and `9.1.1` are indistinguishable, and
chapter titles are missed. Heading depth is reconstructed from the PDF outline
(27 of 41 books have one) or from the numbering in the heading text.
