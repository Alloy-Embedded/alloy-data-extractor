## ADDED Requirements

### Requirement: alloy-data-extractor SHALL be the single source of truth for Zephyr-DTS extraction

After this change archives, the Zephyr-DTS adapter SHALL exist in alloy-data-extractor only — alloy-codegen SHALL contain neither `sources/zephyr_dts.py` nor `sources/zephyr_pinctrl.py`.  The Nordic nRF52 admission SHALL flow through the extractor's `(nordic, nrf52)` registration exclusively.  Pinctrl decoders for Nordic (`NRF_PSEL`) and STM32 (`STM32_PINMUX`) SHALL live in `extractors/zephyr_dts/pinctrl.py`.

#### Scenario: Nordic nRF52 admitted via the extractor

- **WHEN** the pipeline runs for `nrf52840`
- **THEN** the canonical IR loads from `vendors/nordic/nrf52/devices/nrf52840.yml`
- **AND** alloy-codegen SHALL contain no `zephyr_dts` or `zephyr_pinctrl` module
- **AND** the parity gate SHALL stay green for nrf52840
