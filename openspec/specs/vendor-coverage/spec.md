# vendor-coverage Specification

## Purpose
TBD - created by archiving change add-riscv-community-svd-extractor. Update Purpose after archive.
## Requirements
### Requirement: alloy-data-extractor SHALL admit community RISC-V MCUs via CMSIS-SVD

The extractor SHALL register the existing CMSIS-SVD extractor against community RISC-V vendors GigaDevice (GD32V), Bouffalo (BL602/702), WCH (CH32V), Kendryte (K210/K230), and Allwinner (D1).  No new parser is required — only per-vendor pin entries and metadata.  `device.schema.json` `identity.core` SHALL accept the values `riscv-rv32imac`, `riscv-rv32imc`, `riscv-rv32imafc`, `riscv-rv64gc`.

#### Scenario: A GD32V chip extracts via CMSIS-SVD

- **WHEN** the extractor runs for `gd32vf103cbt6`
- **THEN** the canonical YAML carries `identity.core: riscv-rv32imac`
- **AND** loads from `vendors/gigadevice/gd32vf1/devices/gd32vf103cbt6.yml`

### Requirement: alloy-data-extractor SHALL support last-resort PDF datasheet scraping for chips with no machine-readable source

The extractor SHALL ship a `datasheet-pdf` `Extractor` that scrapes vendor PDF reference manuals via pdfminer.six + per-vendor templates and produces canonical YAML.  Every YAML produced this way SHALL carry `provenance.source_id: datasheet-pdf-scrape` and `provenance.confidence: low`.  `device.schema.json` SHALL be extended with an optional `provenance.confidence` field accepting `high`, `medium`, `low`.

#### Scenario: PDF-scraped YAMLs are explicitly low-confidence

- **WHEN** a chip is admitted via the datasheet PDF extractor
- **THEN** its YAML SHALL carry `provenance.confidence: low`
- **AND** alloy-codegen SHALL refuse to consume the YAML unless invoked with `--accept-low-confidence`

