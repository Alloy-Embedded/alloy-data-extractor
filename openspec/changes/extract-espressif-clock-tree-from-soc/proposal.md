# Extract Espressif Clock Tree from SoC Headers

## Why

Espressif YAMLs carry **2-5 `clock_nodes` for 37-54
peripherals** (esp32: 2, esp32c3: 5, esp32s3: 3,
esp32-wroom32: 2).  Compare to STM32G0 (8 nodes for 15
peripherals) or RP2040 (8 nodes for 22 peripherals): the
Espressif clock tree is rendered at ~5% density of what the
silicon actually has.

Real ESP32-class devices have a rich clock tree:

* PLL_CLK, XTAL_CLK, RTC_8M_CLK, RTC_32K_CLK roots
* CPU_CLK (selectable from PLL/XTAL/8M)
* APB_CLK (CPU-derived)
* Per-peripheral mux + divider (UART_CLK, SPI_CLK, …)
* Per-peripheral gate (PERIP_CLK_EN0/1)

esp-idf already ships this as a structured graph:

* `components/soc/esp32{,c3,s3}/include/soc/clk_tree_defs.h`
  declares every clock-source enum.
* `components/soc/esp32{,c3,s3}/clk_tree_hal.c` declares the
  per-peripheral multiplexers + gates.
* `components/hal/include/hal/clk_tree_hal.h` defines the
  shared HAL contract.

The current `esp_idf` extractor in alloy-data-extractor scrapes
peripheral instances but skips the clock tree entirely.  Result:
`runtime_clock_config.hpp` for esp32 emits a near-empty graph;
peripheral clock bindings are unresolvable.

## What Changes

- Extend `alloy_data_extractor.extractors.esp_idf` with a
  `parse_clk_tree(esp_idf_root, soc) -> ClockTree` step that
  walks `soc/<chip>/include/soc/clk_tree_defs.h` +
  `clk_tree_hal.c`.
- Project the parsed tree onto the canonical IR's:
  - `device.clock_nodes` (PLL/XTAL/RTC/CPU/APB + per-peripheral
    leaves)
  - `device.clock_selectors` (CPU source mux,
    per-peripheral source mux)
  - `device.clock_gates` (PERIP_CLK_EN0/1 bits)
  - `device.peripheral_clock_bindings` (the actual UART_CLK →
    UART, SPI_CLK → SPI mappings)
  - `device.system_clock_profiles` (PLL @ 80 / 160 / 240 MHz
    profiles already documented in the SoC reference manual)
- Re-extract YAMLs for esp32, esp32c3, esp32s3, esp32-wroom32.
- Expected delta: 2-5 clock_nodes → 30+ per device; full
  per-peripheral clock-binding coverage.

## Impact

After this lands:

* `runtime_clock_config.hpp` for Espressif gains a real
  multi-source clock graph instead of the bootstrap stub.
* `runtime_clock_graph.hpp` traces every peripheral back to
  its root clock for compile-time validation.
* The `ValidClockSource<Peripheral, Source>` concept added by
  `add-additional-validity-concepts` actually has data to
  enforce on Espressif targets.
* CPU frequency scaling (80/160/240 MHz) becomes a typed
  compile-time choice instead of a runtime poke.

Lifts esp32/c3/s3/wroom32 from Grade C to Grade B in the
audit (`tier_data_classes` and clock_tree gaps both shrink).

## What this DOES NOT do

- Does not extract Espressif tier 2/3/4 (UART parity, I2C
  speed, etc).  Those go through the planned
  `extract-espressif-tier-data-from-soc` follow-up — same
  source repo, different target IR fields.
- Does not handle ESP32-H2 / ESP32-C6 / ESP32-P4.  Each chip
  has its own clk_tree variant and gets admitted in a separate
  change.
- Does not change the canonical IR schema.  Every field
  consumed already exists.
