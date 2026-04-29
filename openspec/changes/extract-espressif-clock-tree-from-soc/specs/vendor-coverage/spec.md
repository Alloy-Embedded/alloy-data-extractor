## ADDED Requirements

### Requirement: The esp_idf extractor SHALL project the SoC clock tree

The `esp_idf` extractor SHALL parse `components/soc/<chip>/include/soc/clk_tree_defs.h`,
`components/soc/<chip>/clk_tree_hal.c`, and
`components/hal/<chip>/include/hal/clk_gate_ll.h` from the esp-idf source
tree and SHALL project the resulting clock graph onto the canonical IR's
`device.clock_nodes`, `device.clock_selectors`, `device.clock_gates`,
`device.peripheral_clock_bindings`, and `device.system_clock_profiles`
fields for every Espressif device admitted via the extractor.

#### Scenario: esp32 carries a multi-source CPU clock graph

- **WHEN** the esp_idf extractor processes esp32
- **THEN** the resulting canonical IR's `device.clock_nodes`
  count SHALL be at least 30
- **AND** `device.clock_selectors` SHALL include a `cpu_clk`
  selector with `parent_options` listing PLL_CLK, XTAL_CLK,
  RTC_8M_CLK
- **AND** `device.system_clock_profiles` SHALL contain at
  least 3 entries (`default_pll_80mhz`, `default_pll_160mhz`,
  `default_pll_240mhz`)

#### Scenario: esp32c3 caps at 160 MHz CPU and emits two profiles

- **WHEN** the esp_idf extractor processes esp32c3
- **THEN** `device.system_clock_profiles` SHALL contain at
  least 2 entries (`default_pll_80mhz`, `default_pll_160mhz`)
- **AND** there SHALL NOT be a 240 MHz profile (the C3
  silicon doesn't support it)

#### Scenario: peripheral clock bindings cover the admitted peripheral set

- **WHEN** the esp_idf extractor processes any Espressif
  device
- **THEN** at least 80% of the admitted peripherals in
  `device.peripherals` whose class is one of UART/SPI/I2C/I2S/
  LEDC/RMT/TIMG/MCPWM SHALL have a matching row in
  `device.peripheral_clock_bindings`
- **AND** every binding SHALL reference a clock node that
  exists in `device.clock_nodes`
