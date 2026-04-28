## ADDED Requirements

### Requirement: alloy-data-extractor SHALL admit TI MSP430 16-bit MCUs

The extractor SHALL register a `msp430` `Extractor` consuming TI SysConfig metadata + MSP430 device-headers and producing canonical YAML for the MSP430 family (~200 chips).  `device.schema.json` `identity.core` SHALL accept `msp430` as a valid value.

#### Scenario: A representative MSP430 chip extracts to canonical YAML

- **WHEN** the extractor runs for `msp430fr5994`
- **THEN** the canonical YAML carries `identity.core: msp430`
- **AND** validates against the schema
