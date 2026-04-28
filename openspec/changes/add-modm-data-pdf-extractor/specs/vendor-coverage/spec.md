## ADDED Requirements

### Requirement: alloy-data-extractor SHALL support last-resort PDF datasheet scraping for chips with no machine-readable source

The extractor SHALL ship a `datasheet-pdf` `Extractor` that scrapes vendor PDF reference manuals via pdfminer.six + per-vendor templates and produces canonical YAML.  Every YAML produced this way SHALL carry `provenance.source_id: datasheet-pdf-scrape` and `provenance.confidence: low`.  `device.schema.json` SHALL be extended with an optional `provenance.confidence` field accepting `high`, `medium`, `low`.

#### Scenario: PDF-scraped YAMLs are explicitly low-confidence

- **WHEN** a chip is admitted via the datasheet PDF extractor
- **THEN** its YAML SHALL carry `provenance.confidence: low`
- **AND** alloy-codegen SHALL refuse to consume the YAML unless invoked with `--accept-low-confidence`
