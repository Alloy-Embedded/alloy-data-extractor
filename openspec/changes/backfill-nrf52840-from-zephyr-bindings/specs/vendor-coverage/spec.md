## ADDED Requirements

### Requirement: The Zephyr-DTS extractor SHALL project register + clock-tree data from Zephyr binding YAMLs

When a device admitted via the Zephyr-DTS extractor has
matching binding YAMLs under `dts/bindings/<peripheral>/`, the
extractor SHALL parse those YAMLs and project their
`properties` / `register-map` / `register-fields` blocks onto
the canonical IR's `device.registers` and
`device.register_fields`.  When the family also ships a
Zephyr clock-tree binding (e.g.
`zephyr/include/zephyr/dt-bindings/clock/<vendor>_clock.h`),
the extractor SHALL build the canonical
`device.clock_nodes` / `device.clock_selectors` /
`device.clock_gates` from the constants there and SHALL bake at
least one default `system_clock_profiles` entry capturing the
post-reset clock state.

#### Scenario: nrf52840 register density matches Nordic Product Spec

- **WHEN** the Zephyr-DTS extractor processes nrf52840
- **THEN** the resulting canonical IR's `device.registers` count
  SHALL be at least 200
- **AND** `device.register_fields` count SHALL be at least 600
- **AND** the UART0, SPIM0, TWIM0, TIMER0 peripherals SHALL
  each carry at least 8 registers

#### Scenario: nrf52840 ships a default clock profile

- **WHEN** the Zephyr-DTS extractor processes nrf52840
- **THEN** the resulting canonical IR's
  `device.system_clock_profiles` SHALL contain at least one
  profile (HFCLK = 64 MHz post-reset)
- **AND** `device.clock_nodes` SHALL contain at least 10 nodes
  rooted at `clock-root` (HFCLK / LFCLK / PLL / HFXO / LFXO
  + sub-trees)

#### Scenario: nrf52840 carries EasyDMA bindings for every DMA-capable peripheral

- **WHEN** the Zephyr-DTS extractor processes nrf52840
- **THEN** the resulting canonical IR's
  `device.dma_bindings` SHALL contain at least 10 entries
- **AND** every entry SHALL have `controller="EASYDMA"` (the
  synthetic per-peripheral controller for nRF52)
