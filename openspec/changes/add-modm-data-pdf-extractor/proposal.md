# Add modm-data PDF Datasheet Extractor

## Why

A long tail of MCUs has **no machine-readable source**: no SVD,
no ATDF, no CMSIS-Pack, no DTS.  modm-data (the modm project's
sibling repo) demonstrated that vendor PDF reference manuals can
be scraped into structured peripheral / register / pinmux data.
Adopting the same approach lets alloy cover chips that no other
framework reaches.

This is a **stretch** capability: opportunistic, contributor-driven,
not on a fixed schedule.

## What Changes

- New extractor `alloy_data_extractor.extractors.datasheet_pdf`
  that uses pdfminer.six + heuristics + per-vendor templates to
  scrape register tables.
- Extractor produces YAML with explicit lower-confidence
  provenance: `provenance.confidence: low` and
  `provenance.source_id: datasheet-pdf-scrape`.
- Schema bumps to add the optional `provenance.confidence` field
  (no break for existing YAMLs).
- Per-vendor template subdirectory with regex / table-shape hints.

## Impact

- alloy-data-extractor: +~1,500 LOC (PDF parsing is verbose).
- alloy-devices-yml: opportunistic additions only.
- Codegen-side: low-confidence YAMLs may be excluded from
  emit by default, requiring an explicit opt-in.

## What this does NOT do

- Does not auto-scrape every PDF.  Each chip is opt-in via
  template.
- Does not replace SVD / ATDF / DTS where available.
