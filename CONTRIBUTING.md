# Contributing

Two ways in. Most people want the first one.

- **[Adding material](#adding-material)** — you have a book, some slides or an
  exam and want it searchable. No tooling, no command line.
- **[Contributing code](#contributing-code)** — you want to change how the
  thing works.

---

## Adding material

Drag files into the private inbox on Hugging Face:
**[Club-de-la-media-luna/master_kb-inbox](https://huggingface.co/datasets/Club-de-la-media-luna/master_kb-inbox)**

You need a Hugging Face account and an invitation to the organisation. Ask in
the group chat; it takes a minute. Nothing else — no git, no Python, no
command line.

### The one rule: put it in the right folder

```
DRL/basic/sutton-barto-reinforcement-learning-2018.pdf
IAP/extra/koller-friedman-probabilistic-graphical-models.pdf
MGP/slides/tema-3-vaes.pdf
MP/exams/2024-enero.pdf
```

`<COURSE>/<kind>/<file>` — that path is the whole contribution. It carries the
two things the pipeline cannot work out for itself: **which course** the
material belongs to, and **how authoritative** it is.

A file dumped at the top level is not lost, but somebody has to sit and
classify it by hand, which is the slow part. The folder takes you five seconds
and saves that.

### Course codes

| | |
| --- | --- |
| `DRL` | Deep Reinforcement Learning |
| `EE` | Ética y explicabilidad |
| `GI` | Geometría de la información |
| `IAG` | Inteligencia artificial geométrica |
| `IAP` | Inteligencia artificial probabilística |
| `IM` | Ingeniería de modelos |
| `MD` | Modelos diferenciales |
| `MGP` | Modelos generativos profundos |
| `MP` | Métodos probabilísticos |

If a book is on two courses' reading lists, drop it under **either one** — say
so in the sidecar (below) if you like. It is stored and indexed once regardless,
carrying both course codes.

### Kinds

| | |
| --- | --- |
| `basic/` | On the *bibliografía básica* of the guía docente |
| `extra/` | On the *bibliografía complementaria* |
| `slides/` | Lecture slides |
| `exams/` | Past exams, problem sets with solutions |

Only `basic/` is indexed today. The others are accepted now so that adding them
later is an append rather than a re-ingest — upload them, they will keep.

**Unsure whether something is basic or complementary?** Put it in `extra/` and
say so. Wrongly-basic material pollutes what everyone searches; wrongly-extra
material just waits.

### Filenames

Lowercase, hyphens, no spaces, and recognisable six months from now:

```
good:  murphy-probabilistic-machine-learning-vol-2-2023.pdf
bad:   Book1.pdf   scan (3).pdf   IMG_20240115.pdf
```

Don't worry about matching an existing naming scheme exactly. Duplicates are
detected by content hash, so re-uploading a book somebody already added costs
nothing and breaks nothing.

### Optional: a sidecar, if the filename doesn't say enough

Next to `whatever.pdf`, a `whatever.txt` containing one line:

```
Murphy, K. P. — Probabilistic Machine Learning: Advanced Topics (2023)
```

That line becomes the entry in the course's bibliography ledger, and therefore
part of every citation the system returns. Skip it and one gets generated from
the filename — legible, just uglier.

Add a second line if there is something worth knowing:

```
Murphy, K. P. — Probabilistic Machine Learning: Advanced Topics (2023)
Also on the MGP reading list. Chapters 1-12 only, the scan stops there.
```

### What not to upload

- **Nothing under 20 pages of front matter.** Two entries in the ledger are
  truncated preview PDFs that were marked as acquired; they are worse than an
  honest gap, because the system reports coverage it does not have.
- **Nothing you would not put in a private group folder.** This corpus is
  course material for one master's programme, held privately for the people
  studying it.
- **Never make the repository public.** Not the inbox, not the derived
  artifacts. The index counts too: embeddings can be inverted back towards
  approximations of the text they were built from, so a public index of these
  books is a weaker form of publishing the books. See
  [ADR-0001](./docs/adr/0001-public-code-private-data.md).

### What happens next

Whoever is maintaining the corpus runs the ingestion — the files are filed into
`master_kb`, recorded in the course ledgers, converted, chunked, embedded and
published. It costs about 25 minutes of GPU time plus conversion, so it happens
in batches rather than per upload. Your material shows up in everyone's
`rag search` after the next `rag pull`.

If you want to run that yourself, see
[docs/onboarding.md](./docs/onboarding.md).

---

## Contributing code

```sh
uv sync --extra index --extra mcp --extra publish
make test      # pytest
make lint      # isort, black, mypy, flake8, ruff, complexipy, pylint
```

Both must be clean before a pull request. Lint is held at 10.00/10 and mypy at
`strict`; neither is negotiable by adding an ignore, unless the ignore comes
with a comment saying what it is protecting against.

**Tests come first.** Write the failing test, watch it fail, then write the
code that passes it. A test written afterwards proves the code does what it
does, not what it should.

**Read [CONTEXT.md](./CONTEXT.md) before naming anything.** The vocabulary is
fixed on purpose — a Book is not a document, a Course is not a subject, a Child
chunk is not a passage. Consistent names are why the codebase can be read at
all.

**Comments explain why, not what.** If a decision looks odd, the comment says
what it is defending against. If it does not look odd, it does not need a
comment.

Design decisions live in [docs/adr/](./docs/adr/). If you are about to
contradict one, that is fine — write the ADR that supersedes it, with the
reason. If you are about to contradict one by accident, the ADR is there to
stop you.
