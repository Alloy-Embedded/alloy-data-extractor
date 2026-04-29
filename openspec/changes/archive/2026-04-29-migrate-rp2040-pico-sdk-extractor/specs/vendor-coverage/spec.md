## ADDED Requirements

### Requirement: alloy-data-extractor SHALL own RP2040 Pico SDK extraction

The extractor SHALL register one `pico-sdk` `Extractor` covering `(raspberrypi, rp2040)`.  The two admitted RP2040 devices SHALL flow through this extractor exclusively after the change archives.  alloy-codegen SHALL contain no RP2040-specific parsing logic and no `_build_rp2040_device_ir` callable.

#### Scenario: RP2040 admitted via the extractor

- **WHEN** the pipeline runs for `pico` or `rp2040`
- **THEN** the canonical IR loads from the matching YAML
- **AND** the single-core-perspective bring-up descriptor is preserved
- **AND** the parity gate stays green for both devices
