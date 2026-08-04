# One extraction path: mineru for every book

Every book goes through mineru, including plain prose. The `prose` extraction
tier and its PyMuPDF fast path are dropped. `extraction_tier` survives as a
descriptive label — `born_digital` or `scan`, from a text-layer probe — recorded
in metadata so scanned books can be flagged as lower-confidence, but it no
longer routes anything.

## Considered Options

The tiered design assumed prose was cheap enough to be worth a separate path.
M2 measured the difference: mineru converts prose at 0.96 s/page, so the entire
1,434-page prose tier costs **23 minutes of a ~12-hour run — about 3%**. PyMuPDF
would save roughly 22 minutes.

Against that, PyMuPDF produces no `content_list.json`: no typed blocks, no
`page_idx`, no `equation` boundaries, and no `aside_text` to discard. A second
path would emit structurally poorer Markdown through different assembly code,
and the two would drift.

Automatic prose-versus-maths classification was also attempted and abandoned.
Maths-symbol density cannot separate the two: Sagan's *Calculus of Variations*,
Gelfand & Fomin, Kloeden & Platen and Boothby all score **0.0 maths symbols per
1000 characters**, identical to *Kubernetes Up & Running*. Their PDFs encode
mathematics in Type 1 fonts whose glyphs carry no Unicode mapping, so a text
layer extracts latin noise rather than `∑∫`. Any threshold that catches them
also catches prose.

## Consequences

Misclassification cost was asymmetric and is now zero: sending a prose book to
mineru wastes seconds, while sending a maths book to PyMuPDF destroys its
equations. Removing the decision removes the failure mode.

The corpus table in the design still lists three tiers because they describe
what the material *is*. Only two of them — `born_digital` and `scan` — are now
detected, and neither changes which tool runs.
