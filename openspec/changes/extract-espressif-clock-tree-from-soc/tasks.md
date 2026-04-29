# Tasks — extract-espressif-clock-tree-from-soc

## Phase 1: Parse clk_tree_defs.h

- [ ] 1.1 Add `parse_clk_tree_defs(soc_dir) -> ClockTreeRaw`
      helper to `alloy_data_extractor.extractors.esp_idf`.
      Walk `components/soc/<chip>/include/soc/clk_tree_defs.h`
      and extract every `enum soc_*_clk_src_t` along with the
      enum members.
- [ ] 1.2 Map the enums onto the canonical clock-node ID
      vocabulary (PLL_CLK / XTAL_CLK / RTC_8M_CLK / etc).
- [ ] 1.3 Build the parent-child relations from the natural
      hierarchy: PLL is a child of XTAL, CPU_CLK selects from
      PLL or XTAL or RTC_8M, APB_CLK is derived from CPU_CLK.

## Phase 2: Parse clk_tree_hal.c

- [ ] 2.1 Add `parse_clk_tree_hal(soc_dir) -> PeripheralClockMap`
      helper.  Walk `components/soc/<chip>/clk_tree_hal.c` for
      the `<chip>_clk_tree_<peripheral>_get_src()` functions.
- [ ] 2.2 Each function reveals which clock sources a peripheral
      can select from + the field that controls the mux.
      Project these into `device.clock_selectors` rows.
- [ ] 2.3 Walk `components/hal/<chip>/include/hal/clk_gate_ll.h`
      for the per-peripheral `_clk_en_set()` macros — those
      give the gate register / bit.  Project into
      `device.clock_gates`.

## Phase 3: System clock profiles

- [ ] 3.1 Bake three default `system_clock_profiles` per
      Espressif device:
      - `default_pll_80mhz`: CPU=80 MHz, APB=80 MHz
      - `default_pll_160mhz`: CPU=160 MHz, APB=80 MHz
      - `default_pll_240mhz`: CPU=240 MHz, APB=80 MHz (S3
        only; not on C3 which caps at 160 MHz)
- [ ] 3.2 esp32-c3 has a different mux (no 240 MHz path); make
      the helper chip-aware.

## Phase 4: Peripheral clock bindings

- [ ] 4.1 For every peripheral in `device.peripherals` whose
      class has a clock-tree entry (UART/SPI/I2C/I2S/LEDC/
      RMT/TIMG/MCPWM), emit a `peripheral_clock_bindings`
      row tying the peripheral to its mux + gate.
- [ ] 4.2 Skip "always-on" peripherals (RTC, CRYPTO, etc) —
      they don't have software-controlled gates.

## Phase 5: Re-extraction + verification

- [ ] 5.1 Run pipeline for esp32, esp32c3, esp32s3,
      esp32-wroom32.
- [ ] 5.2 Verify each YAML carries:
      - `>= 30 clock_nodes`
      - `>= 10 clock_selectors`
      - `>= 20 clock_gates`
      - `>= 3 system_clock_profiles` (2 for c3)
      - `>= 80% of admitted peripherals` covered by
        `peripheral_clock_bindings`
- [ ] 5.3 Round-trip via
      `alloy_codegen.sources.alloy_devices_yml.load_canonical_device`.

## Phase 6: Spec + final checks

- [ ] 6.1 Spec delta in
      `specs/vendor-coverage/spec.md` — esp_idf extractor
      SHALL project the clock tree from soc/clk_tree_defs.h.
- [ ] 6.2 `openspec validate
      extract-espressif-clock-tree-from-soc --strict` passes.
- [ ] 6.3 `pytest -q` + `ruff check` clean.
- [ ] 6.4 Push regenerated YAMLs to alloy-devices-yml.
