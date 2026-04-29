# Tasks — complete-stm32-tier-coverage

## Phase 1: SVD `<enumeratedValues>` projection (universal)

- [ ] 1.1 Extend `cmsis_svd._register_and_field_records` to walk
      every `<field><enumeratedValues><enumeratedValue>` block.
      Build a flat `register_field_enumerations` list with
      `(field_id, name, raw_value, description, provenance)`
      rows, sorted by `(field_id, raw_value)`.
- [ ] 1.2 Handle SVD's `<enumeratedValues derivedFrom="...">`
      inheritance — derived enumeration sets reuse the base
      set's rows under the derived field's `field_id`.
- [ ] 1.3 Honor SVD's `<usage>` element on `<enumeratedValues>`
      (`read`, `write`, `read-write`); when both read and write
      enums exist, emit two separate row groups tagged with
      `usage` so consumers can pick.
- [ ] 1.4 Wire the new field into `extract_device()` payload
      (top-level key `register_field_enumerations`) and add it
      to the canonical-yaml `_TOP_LEVEL_KEY_ORDER` after
      `register_fields`.
- [ ] 1.5 Update the schema (`device.schema.json`) to declare
      the optional `register_field_enumerations` array — minor
      bump to `1.4.0` (additive optional).
- [ ] 1.6 Tests: per-form (`<enumeratedValues>` with values,
      with `derivedFrom`, with `<usage>`), against synthetic
      SVD + against the cached `STM32G071.svd`.  Expected
      counts: ≥ 500 enum rows for stm32g071.
- [ ] 1.7 Verify the rp2040, esp32, mimxrt1062 extractions
      still pass schema validation after the schema bump.

## Phase 2: stm32-tier secondary extractor

- [ ] 2.1 Create `extractors/stm32_tier.py` registered as
      secondary (`families=(("__stm32_tier_secondary__",
      "__stm32_tier_secondary__"),)`).  It does not win the
      resolver; the merge engine invokes it explicitly.
- [ ] 2.2 Define per-IP-version mapping tables under
      `extractors/stm32_tier_mappings.py`:
      - `USART_V3_*_MAPPING` — `(field_id_pattern, target_field,
        projection_fn)` rows for usart_v3_x family.
      - `ADC_V3_*_MAPPING` — same for adc_v3_x.
      - `SPI_V3_*_MAPPING` — same.
      - `GPTIMER_V3_*_MAPPING` — basic timers (TIM2, TIM3, TIM6,
        TIM7, TIM14, TIM15, TIM16, TIM17 on G0).
      - `ADVTIMER_V3_*_MAPPING` — advanced timers (TIM1, TIM8 on
        F4 / F7).
      - Initial coverage: ≥ 1 IP version per peripheral class on
        STM32G0 + STM32F4.
- [ ] 2.3 Implement projection helpers per tier field:
      - `_project_resolution_options(enum_rows) -> tuple[dict]`
        returning `[{value_bits, raw_value, name}]`.
      - `_project_sample_time_options(enum_rows)`.
      - `_project_oversampling_options(enum_rows)`.
      - `_project_external_triggers(enum_rows, peripheral_kind)`.
      - `_project_uart_data_bits(m0_rows, m1_rows)` — USART
        encodes data-bits across CR1.M0 + CR1.M1 (3 bits = 5/6/
        7/8/9).
      - `_project_uart_parity(pce_rows, ps_rows)`.
      - `_project_uart_stop_bits(stop_rows)`.
      - `_project_uart_baud_clock_sources(rcc_ccipr_rows)`.
      - `_project_spi_baud_prescaler(br_rows)`.
      - `_project_timer_trigger_sources(ts_rows)`.
      - `_project_timer_master_outputs(mms_rows)`.
      - `_project_pwm_alignment_options(cms_rows)`.
- [ ] 2.4 Computed projections (no enum needed):
      - `_compute_timer_prescaler_options(psc_field_width)` —
        emit `[{prescaler_value: 1, raw_value: 0}, …,
        {prescaler_value: 65536, raw_value: 65535}]` for
        16-bit PSC; sparse rendering (every power of 2 + a few
        notable values) to keep the array tractable.
      - `_compute_pwm_deadtime_options(dtg_field_width)` — emit
        `[{deadtime_ticks: i, raw_value: i} for i in
        range(2**dtg_width)]`.
- [ ] 2.5 Field-presence detection for mode flags:
      - `timer_mode_flags`:
        - `supports_repetition_counter` ← peripheral has
          `register:tim{n}:rcr`
        - `supports_dma_burst` ← peripheral has `register:tim{n}:
          dcr` + `dmar`
        - `supports_xor_input` ← peripheral has `field:tim{n}:
          cr2:ti1s`
      - `pwm_mode_flags`:
        - `supports_complementary_outputs` ← peripheral has
          BDTR.MOE + CCER.CCxNE pattern
        - `supports_break_input` ← peripheral has BDTR.BKE
        - `supports_break_input_2` ← peripheral has BDTR.BK2E
        - `supports_dead_time_insertion` ← peripheral has
          BDTR.DTG
- [ ] 2.6 Resolve peripheral IP versions: read
      `cubemx_peripherals[*].ip_version` from the merged
      payload (Phase 3.5 of the cubemx work) and dispatch the
      right mapping table.
- [ ] 2.7 Tests:
      - Per-projection unit tests with synthetic enum input.
      - Per-IP-version integration test against `STM32G071.svd`.
      - End-to-end via `merge_payloads` confirms the merged
        payload carries `adc_resolution_options` (≥4 rows),
        `uart_data_bits_options` (≥3 rows),
        `timer_master_outputs` (≥6 rows), `pwm_alignment_options`
        (≥4 rows) for stm32g071rb.

## Phase 3: CubeMX ADC internal channels

- [ ] 3.1 Extend `stm32_cubemx._parse_mcu_xml` to extract
      internal-channel pins.  `<Pin>` with `Type="Reset"` or
      `Type="MonoIO"` whose name matches `VrefInt|TempSensor|
      TempSens|VBat|Vbat` and whose child `<Signal>` has
      `Name="ADC{n}_IN_{kind}"` or `Name="ADC{n}_INP_{kind}"`.
- [ ] 3.2 Project as `adc_internal_channels[]` rows:
      `{peripheral: "ADC{n}", channel_index: <int>, kind:
      "temperature_sensor"|"vrefint"|"vbat"}`.  Channel index
      is parsed from the signal name suffix
      (`ADC1_IN16` → `channel_index=16`); when the signal carries
      a symbolic suffix without a number, fall back to the
      family table maintained in Phase 5.
- [ ] 3.3 Tests:
      - Synthetic CubeMX MCU XML covering all 3 internal-channel
        kinds.
      - Real DB test against the locally installed CubeMX —
        STM32F407 (3 internal channels), STM32G071 (3),
        STM32F0 series (1).

## Phase 4: stm32-cmsis-headers extractor

- [ ] 4.1 Create `extractors/stm32_cmsis_headers.py` registered
      as secondary `("__stm32_cmsis_headers_secondary__",
      "__stm32_cmsis_headers_secondary__")`.  Path resolver
      accepts `--source stm32-cmsis-device-<family>=<root>`
      and walks for the per-chip `stm32<part>xx.h` matching
      the request's device.
- [ ] 4.2 Parse `#define <NAME> ((uintNN_t*)(0x<addr>UL))`
      forms — anchor on the trailing `_ADDR` / `_BASE`
      suffixes.  Filter against a known calibration-name set:
      `TEMPSENSOR_CAL[12]_ADDR`, `TEMPSENSOR_CAL[12]_TEMP`,
      `VREFINT_CAL_ADDR`, `VREFINT_CAL_VREF`,
      `VREFINT_CAL_TEMP`.
- [ ] 4.3 Project parsed constants into:
      - `adc_calibration_data_points[]` rows.
      - `adc_calibration_context.{vrefint_nominal_mv,
        cal_voltage_mv, cal_temp_low_celsius,
        cal_temp_high_celsius, peripheral}`.
- [ ] 4.4 Pin manifest entries — one per supported family —
      in `data/source_pins.toml`:
      - `stm32-cmsis-device-g0` ← `STMicroelectronics/cmsis_device_g0`
      - `stm32-cmsis-device-g4` ← `cmsis_device_g4`
      - `stm32-cmsis-device-f4` ← `cmsis_device_f4`
      - `stm32-cmsis-device-l4` ← `cmsis_device_l4`
      - `stm32-cmsis-device-h7` ← `cmsis_device_h7`
      - `stm32-cmsis-device-u5` ← `cmsis_device_u5`
- [ ] 4.5 Tests: synthetic header fixture covering all 6
      calibration constants + a real-fixture test against a
      checked-in stm32g0xx.h excerpt
      (`tests/fixtures/stm32-cmsis-headers/stm32g071xx.h`,
      ≤ 200 lines, license-attributed).

## Phase 5: Family-overlay TOMLs (truly hand-curated only)

- [ ] 5.1 Create `extractors/stm32_overlay.py` —
      secondary EnrichmentExtractor that reads
      `data/vendors/st/<family>/family.toml` and per-device
      overrides at `data/vendors/st/<family>/devices/<device>.toml`
      when present.  Per-row provenance carries
      `source_id="stm32-overlay"` + the TOML path.
- [ ] 5.2 Schema for `family.toml`:
      ```toml
      [adc]
      max_clock_hz = ...
      [uart]
      max_baud_hz = ...
      [i2c]
      speed_options = [...]   # universal 3 modes, may be
                              # overridden per family for fast-plus support
      max_clock_hz = ...
      [system_clock]
      post_reset_profile = { name = ..., sysclk_hz = ...,
                             source = ... }
      ```
- [ ] 5.3 Bootstrap family overlays:
      - `data/vendors/st/stm32g0/family.toml`
      - `data/vendors/st/stm32f4/family.toml`
      - `data/vendors/st/stm32g4/family.toml` (admit-ready)
      - `data/vendors/st/stm32l4/family.toml` (admit-ready)
      - `data/vendors/st/stm32h7/family.toml` (admit-ready)
      - `data/vendors/st/stm32u5/family.toml` (admit-ready)
      Sourced from each family's RM section "Electrical
      characteristics" — values cited as comments in the TOML.
- [ ] 5.4 STM32_MERGE_POLICY — extend the field-priority map to
      route every tier field (Phases 1-5) through the right
      source: SVD-enum-derived → stm32-tier; RM-table constants
      → stm32-overlay; calibration ROM → stm32-cmsis-headers.
- [ ] 5.5 Tests: per-family TOML round-trip; per-field merge
      priority verified against a synthetic primary + the 4
      enrichments stacked.

## Phase 6: I2C timing-preset computation

- [ ] 6.1 Add `extractors/stm32_i2c_timing.py` (pure module, no
      registration).  Implements the I2C TIMINGR formula from
      ST RM:
      `i2c_clk = source_clk / (PRESC + 1)`,
      `tSCLL = (SCLL + 1) / i2c_clk`, `tSCLH = (SCLH + 1) /
      i2c_clk`, plus `SDADEL`/`SCLDEL` derived from the
      tHD;DAT / tSU;DAT requirements per I2C-bus spec.
- [ ] 6.2 Wire the helper into `stm32_overlay`: for each
      `i2c_speed_options[*]` × `system_clock_profiles[*]`
      pair, compute the TIMINGR fields and emit one
      `i2c_timing_presets[]` row.
- [ ] 6.3 Tests: parametric over (100k / 400k / 1M) × (16M /
      48M / 64M / 80M) source-clock; assert the computed
      preset matches ST AN4235 reference table within rounding
      tolerance.

## Phase 7: Bulk re-emit + verification

- [ ] 7.1 Driver script
      `scripts/reemit_stm32_with_full_tier.py` composing the
      pipeline: SVD primary ⊕ cubemx ⊕ cmsis-headers ⊕
      stm32-tier ⊕ stm32-overlay → merge → write_device_yaml.
- [ ] 7.2 Re-emit YAML for each of the 5 admitted ST devices
      to a sandbox output root.  Compare against the existing
      canonical YAML in alloy-devices-yml.
- [ ] 7.3 Tier-coverage assertion: every re-emitted YAML
      carries ≥ 23 tier-2/3/4 fields populated (parity with
      the existing g071rb).  Drift report per-field for any
      mismatch vs the existing canonical.
- [ ] 7.4 Schema validation: every re-emitted YAML passes
      `validate_yaml_file` against the bundled schema.
- [ ] 7.5 Land the re-emitted YAMLs into alloy-devices-yml on
      a feature branch for review (do not push to main).
- [ ] 7.6 Document the new pipeline in
      `docs/stm32-tier-pipeline.md` (or the README) — single
      diagram + table of which extractor owns which field.

## Phase 8: Spec + final checks

- [ ] 8.1 `openspec validate complete-stm32-tier-coverage --strict`
      passes.
- [ ] 8.2 `pytest -q` clean (target ≥ 280 passed).
- [ ] 8.3 Archive — kept open until Phase 7.5 lands the
      regenerated YAMLs in alloy-devices-yml.
