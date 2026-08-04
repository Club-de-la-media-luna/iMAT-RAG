# iMAT-RAG

Retrieval over the reading list of the Máster Universitario en Inteligencia
Artificial (MIA). Given a question about course material, it returns the
passages that answer it, cited to book, section and page. It retrieves; it does
not generate.

## Language

### Corpus

**Course**:
One of the nine MIA subjects, identified by its code (`DRL`, `GI`, `IAP`, `IM`,
`MD`, `MGP`, `MP`, `IAG`, `EE`). Never referred to by its Spanish title in code.
_Avoid_: subject, asignatura, module

**Book**:
A source document in the corpus, identified by a slug and the SHA-256 of its
PDF. A Book belongs to one or more Courses — the same Book is never stored
twice because two Courses list it.
_Avoid_: document, source, paper, text

**Guide**:
The official *guía docente* for a Course — its syllabus, competences,
bibliography and assessment scheme. One per Course.
_Avoid_: syllabus, guía, spec

**Ledger**:
The per-Course record of which bibliography entries have been acquired, and
under which bibliography section they were listed. The authority on whether a
Book is basic or extra.
_Avoid_: bibliography, index, catalogue

**Source tier**:
An ordinal ranking of a Book's authority over what is actually examined:
`slides > exams > guide > basic_book > extra_book`. Higher tiers win when the
corpus disagrees with itself.
_Avoid_: priority, rank, importance, level

**Extraction tier**:
The cost class that routes a Book to a conversion strategy: `prose`, `maths`,
or `scan`. Describes the physical difficulty of reading the PDF, and is
independent of Source tier.
_Avoid_: type, format, difficulty

**Coverage**:
What the corpus is known *not* to contain, per Course. A Course with no
acquired Books has zero Coverage, and the system says so rather than answering
from adjacent material.
_Avoid_: completeness, gaps

### Retrieval

**Child chunk**:
The small unit that is matched against a query. Carries the embedding.
_Avoid_: chunk, passage, fragment, node

**Parent chunk**:
The larger section a Child chunk belongs to, and the unit actually returned to
the caller. Sized to hold a complete derivation or argument.
_Avoid_: context, window, document

**Breadcrumb**:
The heading path locating a chunk inside its Book — `Bishop PRML > 9. Mixture
Models and EM > 9.4 The EM Algorithm in General`. Prefixed to chunk text so
that notation defined earlier in a chapter travels with the chunk.
_Avoid_: path, heading, title, context header

**Page anchor**:
A marker preserved through extraction that binds a position in the converted
Markdown back to a page of the source PDF. What makes a citation resolvable.
_Avoid_: offset, location, position

**Manifest**:
The record of which inputs and which configuration produced the current
artifacts. The answer to "why did retrieval change?".
_Avoid_: metadata, config, lockfile
