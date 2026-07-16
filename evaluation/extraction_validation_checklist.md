# Extraction validation checklist

Use this checklist for each selected local textbook and record the PDF page index separately from
any printed page label.

## Source validation

- [ ] SHA-256 and byte size match the local fixture manifest.
- [ ] Declared and detected media types are PDF.
- [ ] PDF opens without a password and is not corrupt.
- [ ] Several representative pages expose a useful selectable English text layer.
- [ ] Scan-only input fails with the public `unsupported_document` reason.

## Page and structure sampling

- [ ] First content page, a middle page, and the final content page map to the correct zero-based
      PDF index.
- [ ] Printed labels are recorded independently and may be null.
- [ ] Headings, paragraphs, lists, tables, captions, and equations retain reading order.
- [ ] Raw extraction remains available even when retrieval text removes repeated layout noise.
- [ ] Warnings identify malformed or empty elements instead of silently dropping them.

## Asset sampling

- [ ] Every sampled image opens and maps to the correct PDF page.
- [ ] Bounding box and coordinate origin match the source page.
- [ ] Captions remain associated with their image, map, diagram, or photograph.
- [ ] Raster dimensions and canonical thumbnail dimensions preserve aspect ratio.
- [ ] Accessibility state distinguishes decorative, described, and unavailable informative assets.

## Chunk sampling

- [ ] Every chunk resolves to its book, document, run, and at least one page.
- [ ] Table headers and important section headings are retained.
- [ ] Chunk token counts stay below the selected embedding-model limit.
- [ ] Sequence numbers reproduce source order and support neighbor expansion.
- [ ] Re-running the same source/configuration produces the same logical checksums.

## Sign-off

- Reviewer:
- Fixture SHA-256:
- Sampled PDF indexes:
- Known extraction gaps:
- Result: pass / fail
