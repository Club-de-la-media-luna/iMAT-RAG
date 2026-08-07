# Contributing

Two ways in. Most people want the first one.

- **[Adding material](#adding-material)** — you have a book, some slides or an
  exam and want it searchable. No tooling, no command line.
- **[Contributing code](#contributing-code)** — you want to change how the
  thing works.

---

## Adding material

You keep your own repository and share it. Nothing of yours joins this
organisation, and nothing of ours is open to you — we copy across what you
offer, when you tell us it is ready.

All you need is a Hugging Face account. No git, no Python, no command line.

### Four steps, once

1. **Duplicate the template.** Open
   [master_kb-inbox-template](https://huggingface.co/datasets/Club-de-la-media-luna/master_kb-inbox-template),
   click the three dots at the top right, choose **Duplicate this dataset**.
   In the dialog set **Owner** to your own account and **visibility to
   Private**. It arrives with every course folder already made.
2. **Drag your files in**, into the folder that matches (below).
3. **Settings → Collaborators**, add the maintainer with **read** access.
4. **Send the repository name** in the group chat — `yourname/master_kb-inbox`.

After that, adding more material is just step 2 again.

> **Private is not optional.** This is course material we are not free to
> republish. `rag inbox` checks, and refuses to take anything from a public
> repository — so a mistake here means your upload is ignored, not leaked, but
> it does mean nobody gets it.

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

The folders already exist in the template, so this costs you a click rather
than any typing. A file left at the top level is refused and reported, not
filed somewhere plausible — a guess about which course a book serves is a guess
that ends up in somebody's citations.

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

- **No book under 20 pages.** Truncated previews and front matter are refused
  automatically. Two entries in the ledger are already wrong this way, and a
  book that is recorded but cannot answer anything is worse than an honest gap.
  This applies to `basic/` and `extra/` only — a lecture deck, an exam sheet or
  a problem set is legitimately four pages, and most of them are.
- **Nothing you would not put in a private group folder.** This corpus is
  course material for one master's programme, held privately for the people
  studying it.
- **Never make the repository public.** Not yours, not ours. The index counts
  too: embeddings can be inverted back towards approximations of the text they
  were built from, so a public index of these books is a weaker form of
  publishing the books. See
  [ADR-0001](./docs/adr/0001-public-code-private-data.md).

### What happens next

A maintainer runs `rag inbox yourname/master_kb-inbox`. It **copies** what you
offered — your repository is never depended on afterwards, so you can delete it
whenever you like — records each book in its course's bibliography ledger, and
reports anything it refused and why. Then conversion, chunking, embedding and
publishing.

That costs about 25 minutes of GPU time plus conversion, so it runs in batches
rather than per upload. Your material appears in everyone's `rag search` after
the next `rag pull`.

Things that come back to you rather than going in:

| | |
| --- | --- |
| The repository is public | Refused entirely, nothing is taken |
| A file is at the top level | Refused — no course, no tier |
| An unknown course code or kind | Refused rather than guessed |
| A **book** under 20 pages | Refused as front matter; other kinds are kept |
| A file that will not open | Refused, and the rest of the drop still lands |
| Somebody already added it | Skipped, by content hash — not a problem |

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
