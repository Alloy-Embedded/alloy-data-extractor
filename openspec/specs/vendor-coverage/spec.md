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

