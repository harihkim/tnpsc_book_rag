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

Use `--device cuda` to fail fast when a GPU is required. Keep `--device auto` for a notebook that
may fall back to CPU. Keep the generated directory and ZIP together; the manifest is the integrity
boundary the application import service verifies before accepting the package. The importer checks
the source checksum and size against the separately stored PDF, retains the ZIP for replay, and
writes typed pages, content-unit parents, child chunks, and assets through the same persistence
transaction as the CPU worker after the database-v2 migration is complete.

The default child limit is the first pilot candidate. Rechunk the same lossless `docling.json` at
`256` and `384` tokens rather than running PDF conversion twice. Do not use a floating tokenizer
branch: the default is an immutable project revision, and any override is included in the chunking
fingerprint. Existing package-v1 archives remain useful for comparison but are diagnostic-only and
cannot enter the normal v2 importer.

The backend verifier also requires the curriculum metadata in `manifest.json` before it permits an
import. The original PDF may remain a separate content-addressed artifact as long as its SHA-256
and byte size match the manifest source record.
