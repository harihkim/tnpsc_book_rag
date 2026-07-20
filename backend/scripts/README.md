# Offline extraction package

`extract_book.py` runs the Phase 1 Docling extraction without a database, production credentials,
or the backend application environment. Its runtime lives in the dependency-light
`tnpsc_extraction` package and imports no API, database, storage, or OpenTelemetry modules.
It is suitable for a CUDA-enabled Google Colab session or a local GPU workstation.

The output directory uses the intentionally breaking package-v2 contract and contains:

- `manifest.json` with curriculum identity (`title`, `standard`, `subject`, `term`, `language`,
  `publisher`, and `edition`), source SHA-256, separate extraction and chunking fingerprints,
  the pinned tokenizer identifier/revision, parent-child schema versions, counts, and checksums for
  every generated file.
- `docling.json`, preserving the lossless Docling representation with embedded references.
- `pages.jsonl` and `assets.jsonl` with page-linked extraction records.
- `content_units.jsonl` with semantic evidence parents such as definitions, solved examples, and
  complete Markdown-plus-structured tables.
- `chunks.jsonl` with tokenizer-bounded retrieval children and explicit parent references.
- `images/` with canonical extracted picture PNGs and their page/provenance metadata.
- An optional copied source PDF only when `--include-source` is explicitly supplied.

The script refuses to overwrite an existing output directory and writes through a temporary sibling
before publishing the completed package. It never opens a database connection or sends content to a
model provider.

## Google Colab

Clone the repository, enable a CUDA runtime, and install only the extraction dependencies:

```python
!git clone https://github.com/harihkim/tnpsc_book_rag.git
%cd tnpsc_book_rag/backend
!pip install -r scripts/requirements-extraction.txt
```

Upload or mount one PDF, then run:

```python
!python scripts/extract_book.py \
  /content/6th_Science_Term_I.pdf \
  /content/extracted/6th-science-term1 \
  --title "Tamil Nadu State Board Standard 6 Science" \
  --standard 6 \
  --subject Science \
  --term 1 \
  --publisher "Government of Tamil Nadu" \
  --edition "Term I" \
  --device auto \
  --child-max-tokens 256 \
  --parent-soft-tokens 800 \
  --parent-hard-tokens 1200 \
  --archive /content/extracted/6th-science-term1.zip
```

An `HF_TOKEN` is optional. Without one, Hugging Face prints an unauthenticated-download warning and
uses lower Hub rate limits; it does not change chunk content or package verification.

Use `--device cuda` to fail fast when a GPU is required. Keep `--device auto` for a notebook that
may fall back to CPU. Keep the generated directory and ZIP together; the manifest is the integrity
boundary the application import service verifies before accepting the package. The importer checks
the source checksum and size against the separately stored PDF, retains the ZIP for replay, and
writes typed pages, content-unit parents, child chunks, and assets through the same persistence
transaction as the CPU worker after the database-v2 migration is complete.

The first extraction above is the `256`-token pilot variant. Produce the `384`-token comparison
from that verified v2 ZIP without converting the PDF again:

```python
!python scripts/rechunk_book.py \
  /content/extracted/6th-science-term1.zip \
  /content/extracted/6th-science-term1-384 \
  --child-max-tokens 384 \
  --archive /content/extracted/6th-science-term1-384.zip
```

`rechunk_book.py` first verifies the source archive, reuses its exact `docling.json`, page records,
asset metadata, and images, and replaces only `content_units.jsonl`, `chunks.jsonl`, and the
chunking-dependent manifest values. It verifies the staged result before publishing either the
directory or ZIP. The source, output directory, and output ZIP must be distinct, and the command
refuses to overwrite any of them.

The current `textbook-hybrid-v3` policy can also upgrade a verified `textbook-hybrid-v2` archive
without changing its token cap. This is the intended migration for the preserved Standard 6 pilot
packages and does not run Docling again:

```python
!python scripts/rechunk_book.py \
  /content/extracted/6th-science-term1-v2-256.zip \
  /content/extracted/6th-science-term1-v3-256 \
  --child-max-tokens 256 \
  --archive /content/extracted/6th-science-term1-v3-256.zip
```

Version 3 recovers empty formula text from Docling's preserved `orig` value, retains a page-linked
non-retrievable diagnostic for a truly empty formula, recognizes definition prose, keeps an
Example-to-Solution transition in one parent, removes unsafe control characters, excludes text
containing irrecoverable replacement characters, and merges undersized children only within their
already-classified parent. The package-v2 schema remains unchanged and older archives remain valid
inputs to the verifier and rechunk command.

Run the same two-command sequence for Mathematics Term I. Do not run Docling once per token limit,
and do not process the remaining corpus until the pilot configuration has passed retrieval
evaluation. Structural evaluation of all four Standard 6 Term I books favors the 256-token v3
variant for the first embedding pilot: its 95th-percentile child is roughly 189–209 tokens, while
384 removes only 48 children across the four books and produces a much longer tail. Keep the 384
archives as comparison evidence until retrieval evaluation confirms the choice. Do not use a
floating tokenizer branch: the default is an immutable project revision, and any override is
included in the chunking fingerprint. Existing package-v1 archives remain useful for comparison
but are diagnostic-only and cannot enter the normal v2 importer.

## Extract a folder

Use the batch helper when one folder contains books from the same standard and term. It processes
PDFs directly inside that folder, infers the subject from filenames containing `English`,
`Mathematics`/`Maths`, `Science`, or `Social Science`, and refuses ambiguous filenames:

```bash
PYTHON_BIN=.venv/bin/python scripts/extract_folder.sh \
  data/Std_06/term1 \
  /path/to/extracted/std-06-term-1 \
  6 \
  1 \
  --device cpu \
  --rechunk-384
```

In Colab, omit `PYTHON_BIN` because `python` is already available, and normally use
`--device auto` or `--device cuda`. Every book is converted by Docling once at 256 tokens; the
optional 384-token package reuses that verified archive. Complete directory-plus-ZIP pairs are
skipped on a rerun, while partial outputs stop the batch for manual inspection instead of being
overwritten.

The backend verifier also requires the curriculum metadata in `manifest.json` before it permits an
import. The original PDF may remain a separate content-addressed artifact as long as its SHA-256
and byte size match the manifest source record.
