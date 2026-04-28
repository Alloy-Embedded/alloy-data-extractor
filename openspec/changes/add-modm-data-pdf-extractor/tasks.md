# Tasks — add-modm-data-pdf-extractor

## Scaffold (autonomous round)

- [x] S.1 Register `datasheet-pdf` extractor with synthetic
      family binding (invoked explicitly per-template, not
      auto-resolved).
- [x] S.2 Wire scaffold into `pipeline.py` side-effect imports.
- [x] S.3 Test scaffold registration.

## Phase 1: Implementation

- [ ] 1.1 Implement `extractors/datasheet_pdf.py` (pdfminer.six +
      template-based scraper).
- [ ] 1.2 Schema bump: add optional `provenance.confidence`.
- [ ] 1.3 Per-vendor template format under
      `data/datasheet_templates/<vendor>.toml`.
- [ ] 1.4 Demo template: scrape one Holtek HT32 datasheet end-to-end.
- [ ] 1.5 Codegen-side opt-in: `--accept-low-confidence` flag.
- [ ] 1.6 `openspec validate add-modm-data-pdf-extractor --strict`.
- [ ] 1.7 Archive + commit.
