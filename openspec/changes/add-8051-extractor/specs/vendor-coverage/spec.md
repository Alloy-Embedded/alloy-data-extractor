## ADDED Requirements

### Requirement: alloy-data-extractor SHALL admit 8051-derivative MCUs from Nuvoton, SiLabs, and STC

The extractor SHALL register an `intel-8051` `Extractor` covering Nuvoton N76, SiLabs EFM8, and STC15W families.  `device.schema.json` `identity.core` SHALL accept `i8051`.

#### Scenario: A Nuvoton N76 chip extracts to canonical YAML

- **WHEN** the extractor runs for `n76e003at20`
- **THEN** the canonical YAML carries `identity.core: i8051`
- **AND** validates against the schema
