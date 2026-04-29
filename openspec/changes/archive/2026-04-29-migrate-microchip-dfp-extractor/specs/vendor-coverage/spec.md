## ADDED Requirements

### Requirement: alloy-data-extractor SHALL own Microchip DFP/ATDF extraction end-to-end

The extractor SHALL register a single `microchip-dfp` `Extractor` covering `(microchip, avr-da)` and `(microchip, same70)`.  The implementation SHALL split into three modules (`atdf.py` for the XML parser, `avr.py` for AVR8 IR projection, `sam.py` for Cortex-M IR projection) so that future PIC support can reuse `atdf.py` without forking the parser.  After this change archives, alloy-codegen SHALL contain no Microchip-specific parsing logic.

#### Scenario: SAME70 PWM peripherals load byte-identically through the extractor

- **WHEN** the pipeline runs for `atsame70n21b`
- **THEN** the canonical IR loaded from the YAML SHALL carry the same70 PWM peripheral records that the legacy `_build_same70_pwm_peripherals` produced
- **AND** the parity gate SHALL stay green for both same70 variants

#### Scenario: AVR-DA admitted via the extractor

- **WHEN** the pipeline runs for `avr128da32`
- **THEN** the canonical IR loads from `vendors/microchip/avr-da/devices/avr128da32.yml`
- **AND** alloy-codegen SHALL contain no `_build_avr_da_device_ir` callable
