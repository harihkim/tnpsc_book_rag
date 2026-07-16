# Local textbook fixture selection

Phase 0 selects three structurally different English-medium Tamil Nadu State Board textbook
profiles. The PDFs themselves are intentionally ignored: they may be copyrighted, are too large
for normal Git history, and should come from an authorized local copy.

Place local files in this directory using these ignored names:

| Fixture name | Target profile | Why it is selected |
|---|---|---|
| `science-standard-8.pdf` | Standard 8 Science | Headings, prose, tables, diagrams, captions, and equations |
| `social-science-standard-10.pdf` | Standard 10 Social Science | Maps, photographs, timelines, multi-column material, and dense captions |
| `mathematics-standard-6.pdf` | Standard 6 Mathematics | Worked examples, formulas, lists, geometric figures, and compact tables |

Before using a file:

1. Confirm it is English-medium and digitally generated rather than scan-only.
2. Confirm text can be selected and copied from several body pages.
3. Record its SHA-256, page count, edition, source, and redistribution status in
   `fixture_manifest.json` using the adjacent example structure.
4. Keep `redistribution_permitted=false` unless permission is documented.
5. Do not commit the PDF or extracted textbook content.

The Phase 1 extraction gate uses all three profiles. A developer may start with the Science book
for the first vertical slice, but completion requires all three.
