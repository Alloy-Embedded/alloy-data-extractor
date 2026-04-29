# Tasks — backfill-nrf52840-from-zephyr-bindings

## Phase 1: Zephyr binding YAML walker

- [ ] 1.1 Add `parse_zephyr_binding(yaml_path) -> BindingShape`
      helper to `alloy_data_extractor.extractors.zephyr_dts`.
      Parse the YAML's `properties` block + `register-map` /
      `reg` cells.
- [ ] 1.2 Map each binding `compatible` string to a peripheral
      class (e.g., `nordic,nrf-uart` → `uart`).  Re-use the
      existing `COMPATIBLE_MAPS` registry for vendor + family.
- [ ] 1.3 Project each binding's registers into
      `RegisterDescriptor` rows; project nested
      `register-fields` blocks into
      `RegisterFieldDescriptor` rows.

## Phase 2: Nordic clock tree

- [ ] 2.1 Parse `zephyr/include/zephyr/dt-bindings/clock/nrf_clock.h`
      constants → `device.clock_nodes`.  Root is `clock-root`,
      with HFCLK / LFCLK / PLL / HFXO / LFXO subtrees.
- [ ] 2.2 Walk `nrf52840.dtsi` `&hfclk { clocks = <&hfxo>; }`
      style references → `device.clock_selectors` and
      `device.peripheral_clock_bindings`.
- [ ] 2.3 Bake a default `system_clock_profiles` entry:
      `default_hfclk_64mhz` with HFCLK = 64 MHz, sysclk = HFCLK.

## Phase 3: Tier 2/3/4 from datasheet

- [ ] 3.1 Re-use `datasheet_pdf` extractor on
      `tests/fixtures/nordic/nRF52840_PS.pdf` to pull:
      - `uart_data_bits_options` (8 only on nRF52)
      - `uart_parity_options` (none / even)
      - `uart_stop_bits_options` (1, 2)
      - `uart_baud_options` (the explicit baud-rate enum)
      - `i2c_speed_options` (100k, 250k, 400k)
      - `spi_baud_prescaler_options` + frame-size options
- [ ] 3.2 Project these into the canonical IR's tier fields
      with `provenance.source_id = "nordic-product-spec"`.

## Phase 4: EasyDMA bindings

- [ ] 4.1 Add a synthetic `EASYDMA` controller row to
      `device.dma_controllers` (per-peripheral, no central
      hub).
- [ ] 4.2 For every peripheral that has EasyDMA support
      (UART, SPI, I2C, SAADC, PDM, I2S, NFC), create one
      `device.dma_bindings` row pointing to its TX / RX path
      with `controller="EASYDMA"`, `channel_index=None`,
      `request_value=None` (placeholders).

## Phase 5: Re-extraction + verification

- [ ] 5.1 Run the pipeline: `alloy-data-extractor extract
      --vendor nordic --family nrf52 --device nrf52840`.
- [ ] 5.2 Verify the resulting YAML carries:
      - `>=200 registers` and `>=600 register_fields`
      - `>=10 clock_nodes`, `>=1 system_clock_profiles`
      - `>=4 uart_*`, `>=3 i2c_speed_options`,
        `>=4 spi_baud_prescaler_options`
      - `>=10 dma_bindings`
- [ ] 5.3 Round-trip via
      `alloy_codegen.sources.alloy_devices_yml.load_canonical_device`
      to confirm schema-valid IR.
- [ ] 5.4 Run alloy-codegen's `--runtime-cpp-smoke` gate on
      nrf52840.

## Phase 6: Spec + final checks

- [ ] 6.1 Spec delta in
      `specs/vendor-coverage/spec.md` — Zephyr-DTS extractor
      SHALL project register + clock-tree + tier data when a
      device has matching binding YAMLs.
- [ ] 6.2 `openspec validate
      backfill-nrf52840-from-zephyr-bindings --strict` passes.
- [ ] 6.3 `pytest -q` + `ruff check` clean.
- [ ] 6.4 Push regenerated `nrf52840.yml` to alloy-devices-yml.
