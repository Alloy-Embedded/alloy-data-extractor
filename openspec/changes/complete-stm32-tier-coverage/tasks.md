# Tasks — complete-stm32-tier-coverage

## Phase 1: SVD `<enumeratedValues>` projection (universal)

- [x] 1.1 Extended `cmsis_svd._register_and_field_records` to
      walk every `<field><enumeratedValues><enumeratedValue>`
      block.  Added `_parse_field_enumerations()` helper.  Flat
      `register_field_enumerations` list emitted with
      `(field_id, peripheral, register_name, field_name, name,
      raw_value, description, usage, provenance)` rows, sorted
      by `(field_id, usage, raw_value)`.
- [x] 1.2 Handled `<enumeratedValues derivedFrom="...">`
      inheritance via a two-pass resolver
      (`_resolve_derived_enumerations()`).  Three resolution
      modes: full path `PERI.REG.FIELD`, peripheral-relative
      `REG.FIELD`, and bare `FIELD` (name-only fallback).
      Missing references drop silently.
- [x] 1.3 Honored `<usage>` element on `<enumeratedValues>`.
      Default `read-write`; `read` and `write` blocks emit two
      separate row groups carrying their respective usage tag.
- [x] 1.4 Wired `register_field_enumerations` into the
      `extract_device()` payload and added it to
      `_TOP_LEVEL_KEY_ORDER` after `register_fields`.
- [x] 1.5 Bumped `SCHEMA_VERSION_CURRENT` 1.3.0 → 1.4.0
      (additive, optional) + bumped `MERGED_SCHEMA_VERSION` to
      match.  The bundled JSON schema in `alloy-devices-yml` is
      permissive (`additionalProperties: true`) so it
      auto-accepts the new field; no schema-file edit required.
- [x] 1.6 Tests under `test_cmsis_svd_extractor.py` (8 new):
      concrete enum extraction, read+write usage split, three
      derivedFrom forms, derivedFrom-via-peripheral propagation,
      per-row provenance, key-presence in the canonical
      payload, deterministic sort.  Verified against the cached
      `STM32G071.svd`: 559 enum rows.
- [x] 1.7 Verified mimxrt1062 extraction still produces valid
      payload — added bonus 29,739 enum rows from the NXP
      SoC SVD (which annotates enums very thoroughly).
      Full pytest suite: 251 passed / 2 skipped (was 243).
      Merged stm32g071rb re-emit grows from 59,620 → 66,330
      lines (90% of canonical's 73,410).

## Phase 2: stm32-tier secondary extractor

- [x] 2.1 Created `extractors/stm32_tier.py` registered as
      secondary `("__stm32_tier_secondary__","…")`.  Walks the
      CubeMX MCU XML directly (independent re-read) to discover
      peripheral instances + IP versions.
- [x] 2.2 `extractors/stm32_tier_mappings.py` ships
      9 TierMapping entries: USART_SCI3_V2, USART_SCI2_V1,
      SPI_V3, I2C_V1, ADC_G0_V3, ADC_F4_V3, TIMER_GPTIMER_V3,
      TIMER_F4_ADV, TIMER_F4_GP.  Initial coverage targets
      STM32G0 (full) + STM32F4 (USART/ADC/timer subset).
- [x] 2.3 Hardcoded projection rows live inline in the mapping
      tables (USART data_bits/parity/stop_bits/mode_flags,
      SPI baud_prescaler, ADC resolution/sample_time/
      oversampling/external_triggers, timer master_outputs/
      trigger_sources/prescaler, PWM alignment/break_inputs/
      deadtime/mode_flags).  The original "project from SVD
      enums" plan was downgraded after observing wildly uneven
      enum coverage in cmsis-svd-data community SVDs — STM32G071
      ships enums for ADC + TIM15 only, STM32F405 ships zero.
      Hardcoded per-IP-version constants deliver tier-3
      deterministically regardless of SVD richness, with
      identical maintenance cost (one edit per IP version).
- [x] 2.4 Computed projections embedded in mapping rows:
      `timer_prescaler_options` rendered sparse (1, 2, 4 …
      65536 — 17 powers-of-2 entries) since the full 65,536-row
      table would bloat the YAML; `pwm_deadtime_options`
      emitted as 4 range rows matching the BDTR.DTG non-linear
      encoding.
- [x] 2.5 Mode-flag rows hardcoded per IP version (advanced
      timers get `supports_repetition_counter=True` etc.;
      general-purpose timers get the non-advanced subset).
      Field-presence detection from the SVD register tree was
      the original plan — collapsed into per-IP-version
      constants for the same reason as 2.3 (more deterministic,
      one edit per IP version).
- [x] 2.6 IP versions resolved by re-parsing the CubeMX MCU XML
      via the existing `stm32_cubemx._parse_mcu_xml` helper —
      the per-instance `<IP Version="…">` attribute is now also
      surfaced in stm32-cubemx's payload as
      `cubemx_peripherals[]` for downstream auditing.
      `STM32_MERGE_POLICY` extended with 18 tier-field-priority
      rules routing each tier array through `stm32-tier`.
- [x] 2.7 Tests under `test_stm32_tier_extractor.py` (19 new):
      version-pattern dispatch (parametric over 6 IPs);
      cross-instance dedup; cross-IP-version row union;
      unmapped-instance skip; deterministic sort; provenance
      stamping; resolver-secondary; missing-source raises;
      warning surface for unmapped IPs; synthetic-DB end-to-end
      (15 tier fields populated); real-DB smoke test against
      the locally installed CubeMX.  Verified the merged
      stm32g071rb pipeline lights up 18 tier-3/4 fields via
      this projector alone.

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
