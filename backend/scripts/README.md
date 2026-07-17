# Offline extraction package

`extract_book.py` runs the Phase 1 Docling extraction without a database, production credentials,
or the backend application environment. Its runtime lives in the dependency-light
`tnpsc_extraction` package and imports no API, database, storage, or OpenTelemetry modules.
It is suitable for a CUDA-enabled Google Colab session or a local GPU workstation.

The output directory contains:

- `manifest.json` with source SHA-256, runtime/device metadata, extraction fingerprints, counts, and
  checksums for every generated file.
- `docling.json`, preserving the lossless Docling representation with embedded references.
- `pages.jsonl`, `chunks.jsonl`, and `assets.jsonl` for a future production importer.
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
  --device auto \
  --archive /content/extracted/6th-science-term1.zip
```

Use `--device cuda` to fail fast when a GPU is required. Keep `--device auto` for a notebook that
may fall back to CPU. Keep the generated directory and ZIP together; the manifest is the integrity
boundary a production import job must verify before accepting the package.
