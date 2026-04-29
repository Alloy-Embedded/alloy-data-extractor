# Backfill nrf52840 from Zephyr Bindings

## Why

The `nrf52840.yml` in alloy-devices-yml is the only Grade-D
device in the catalog: 7 peripherals admitted, **0 registers,
0 register fields, 0 tier-2/3/4 entries, 0 DMA bindings, 0
clock profiles**.  The Zephyr-DTS extractor that admitted the
device (via `extend-zephyr-dts-vendor-coverage`) only emits
peripheral-instance metadata + interrupt lines — it intentionally
skipped the register-level shape.

Result: every alloy HAL driver targeting nRF52840 produces
`kPresent=true` peripherals with no usable register
references — drivers can't actually read or write registers
on this chip.  nRF52840 is one of the most widely deployed
ARM Cortex-M4 parts (BLE, Thread, Zigbee), so the gap is
material.

The fix doesn't require a new vendor source — Zephyr already
ships the data:

* `nrf52840.dtsi` declares every peripheral instance with its
  base address.
* `dts/bindings/<peripheral>/nordic,*.yaml` declares the
  per-peripheral register layout (offsets, fields, access).
* `zephyr/include/zephyr/dt-bindings/clock/nrf_clock.h`
  declares the canonical clock tree (HFCLK / LFCLK / PLL,
  pre-scalers, gates).
* `zephyr/dts/arm/nordic/<chip>.dts` declares default clock
  profiles.

This change extends the existing `zephyr_dts` extractor to
walk those binding YAMLs and project the data onto the
canonical IR.

## What Changes

- Extend `alloy_data_extractor.extractors.zephyr_dts` with a
  `parse_zephyr_bindings(bindings_dir, peripheral_name) ->
  RegisterDescriptors` step.  Each binding YAML lists
  `properties` keyed by register offset; project them onto the
  canonical IR's `device.registers` + `device.register_fields`.
- Add a Nordic-specific clock-tree extractor: walk
  `nrf_clock.h` constants + `nrf52840.dtsi` `clocks`
  references and build the canonical
  `device.clock_nodes` / `device.clock_selectors` /
  `device.clock_gates`.
- Bake at least one default `system_clock_profiles` entry
  (HFCLK 64 MHz, the post-reset state) so
  `runtime_clock_config.hpp` has something to emit.
- Backfill UART / SPI / I2C tier 2/3/4 from the Nordic
  product specification PDF (already in
  `tests/fixtures/nordic/nRF52840_PS.pdf` — re-use the
  existing `datasheet_pdf` extractor for the small fixed-size
  fields like `parity_options`, `data_bits_options`, `i2c_speed_options`).
- DMA bindings on nRF52 use the EasyDMA pattern (per-peripheral
  pointer + length register, not a central controller).
  Project this into `device.dma_bindings` with synthetic
  `controller="EASYDMA"` rows + an extra capability flag.
- Re-extract `nrf52840.yml` and verify the audit-table grade
  lifts from D to B.

## Impact

After this lands:

* nrf52840 peripherals gain ~200 registers + ~600 fields
  (UART, SPI, I2C, TIMER, RTC, RNG, CRYPTOCELL, …).
* alloy HAL drivers (UART/SPI/I2C/Timer) gain register-level
  write access on nRF52840.
* `runtime_clock_config.hpp` produces a real default clock
  profile instead of empty struct.
* Tier 2/3/4 traits emit real options instead of zero-length
  arrays.

This is the highest-leverage single-device fix in the audit.

## What this DOES NOT do

- Does not extend coverage to nRF53 / nRF54.  Each new chip
  is its own data-extraction job.
- Does not bake the Nordic radio / BLE register set —
  CRYPTOCELL and RADIO peripherals are intentionally skipped
  for now (Bluetooth stack lives in a separate layer of
  the alloy HAL).
- Does not handle pinctrl coverage — the existing
  `decode-zephyr-pinctrl-into-connection-candidates`
  flow already fills `pin_connection_candidates`; this
  change adds register-level data only.
