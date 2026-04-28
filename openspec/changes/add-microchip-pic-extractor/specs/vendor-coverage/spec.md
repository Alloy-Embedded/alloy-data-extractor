## ADDED Requirements

### Requirement: alloy-data-extractor SHALL admit Microchip PIC families through the DFP/ATDF pipeline

The extractor SHALL register `Extractor` instances covering every Microchip PIC family the MPLAB X DFP catalog ships: PIC8/16/18 (8-bit Harvard), PIC24 + dsPIC33 (16-bit modified Harvard), and PIC32MX/MZ/MK (MIPS).  The implementation SHALL reuse the `atdf.py` module shared with AVR + SAM extraction (split by `migrate-microchip-dfp-extractor`).  Coverage SHALL include at least 1,500 PIC8/16/18 chips, 500 PIC24/dsPIC, and 100 PIC32 chips.

#### Scenario: A representative PIC18 chip extracts to canonical YAML

- **WHEN** the bulk pipeline runs for `pic18f47q10`
- **THEN** the canonical IR YAML carries `identity.core: pic18`
- **AND** validates against `device.schema.json`
- **AND** the YAML is byte-identical between two runs of the pinned DFP

### Requirement: PIC core identifiers SHALL be enumerated in the schema

`device.schema.json` `identity.core` SHALL accept the values `pic12f`, `pic16f`, `pic18`, `pic24f`, `dspic33`, `pic32mx`, `pic32mz`, `pic32mk` in addition to the existing ARM / AVR / Xtensa / RISC-V values.

#### Scenario: A PIC32MZ device validates against the schema

- **WHEN** a YAML with `identity.core: pic32mz` is validated
- **THEN** schema validation SHALL succeed
