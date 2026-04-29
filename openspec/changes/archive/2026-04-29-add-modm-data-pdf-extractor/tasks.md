# Tasks — add-modm-data-pdf-extractor

## Phase 1: PDF scraper (autonomous round)

- [x] 1.1 Implement `extractors/datasheet_pdf.py` with
      pdfminer.six text extraction + per-vendor template
      driven scraping (memory map + peripheral base addresses).
- [x] 1.2 Schema: every PDF-sourced YAML carries
      `provenance.confidence: low` + `source_id: datasheet-pdf-scrape`.
- [x] 1.3 Per-vendor template format under
      `data/datasheet_templates/<vendor>.toml`; demo template
      shipped for Holtek HT32.
- [x] 1.4 Tests (`test_datasheet_pdf_extractor.py`): synthetic
      text scraping + memory-map / peripheral / dedup /
      size-unit-conversion + reportlab-rendered PDF round-trip
      (skipped when reportlab missing).

## Phase 2: Codegen-side opt-in

- [x] 2.1 alloy-codegen consumer adds `--accept-low-confidence`
      flag.  Without it, the YAML loader refuses
      `provenance.confidence: low` documents.
- [x] 2.2 Boundary test: low-confidence YAMLs are excluded by
      default from the parity gate + emission stages.

## Phase 3: Register-tree scraping (follow-up)

- [x] 3.1 Modm-data-style table recognition for register-tree
      extraction (much harder; deferred to a dedicated session).

## Phase 4: Validate + archive

- [x] 4.1 `openspec validate add-modm-data-pdf-extractor --strict`.
- [x] 4.2 Pytest green (147/147 + 2 skips).
- [x] 4.3 Archive — kept open until Phase 2 codegen-side
      opt-in lands.
