## ADDED Requirements

### Requirement: The cmsis-svd extractor SHALL emit register-field enumerations

The `cmsis_svd` extractor SHALL walk every
`<field><enumeratedValues><enumeratedValue>` block in the SVD
and project the enumerations onto a top-level
`register_field_enumerations` array carrying
`(field_id, name, raw_value, description, usage, provenance)`
rows.  `<enumeratedValues derivedFrom="...">` SHALL inherit
the base set's rows under the derived field's `field_id`; the
`<usage>` element SHALL be honored — when both `read` and
`write` enumerations exist for the same field, both row groups
SHALL be emitted with their respective `usage` tag so consumers
can pick.  Per-row provenance follows the same convention as
`registers` and `register_fields`.

#### Scenario: STM32G071 ADC.CFGR1.RES emits 4 resolution rows

- **WHEN** the cmsis-svd extractor processes
  `STM32G071.svd`
- **THEN** the resulting payload's
  `register_field_enumerations` SHALL contain 4 rows under
  `field_id = "field:adc1:cfgr1:res"`
- **AND** each row's `(name, raw_value)` SHALL match the SVD's
  declared enumeration for 12-bit / 10-bit / 8-bit / 6-bit
  resolution

#### Scenario: derivedFrom enumerations propagate

- **WHEN** an SVD declares
  `<enumeratedValues derivedFrom="ADC1.SMP1"/>` on
  `ADC2.SMPR1.SMP1`
- **THEN** `register_field_enumerations` SHALL carry the rows
  for both `field:adc1:smpr1:smp1` and `field:adc2:smpr1:smp1`
- **AND** both row groups SHALL share the same `(name,
  raw_value)` pairs

### Requirement: A new stm32-tier secondary extractor SHALL project SVD enumerations into canonical tier arrays

The `stm32-tier` extractor SHALL register as a secondary
EnrichmentExtractor and SHALL consume
`register_field_enumerations` (Phase 1) plus the per-peripheral
`ip_version` resolved by the `stm32-cubemx` extractor.  It
SHALL emit canonical tier-2/3/4 arrays
(`adc_resolution_options`, `adc_sample_time_options`,
`adc_oversampling_options`, `adc_external_triggers`,
`uart_data_bits_options`, `uart_parity_options`,
`uart_stop_bits_options`, `uart_baud_clock_sources`,
`spi_baud_prescaler_options`, `timer_trigger_sources`,
`timer_master_outputs`, `pwm_alignment_options`) for every
peripheral instance whose IP version has a registered mapping
table.  Computed projections (`timer_prescaler_options`,
`pwm_deadtime_options`, `timer_mode_flags`, `pwm_mode_flags`)
SHALL be derived from field-shape / field-presence on the
peripheral's register tree.

#### Scenario: stm32g071rb tier-3 arrays are populated end-to-end

- **WHEN** the merge engine composes the stm32 primary
  extraction with stm32-cubemx + stm32-tier for `stm32g071rb`
- **THEN** the merged payload SHALL carry
  `adc_resolution_options` with at least 4 rows
- **AND** `uart_data_bits_options` with at least 3 rows
- **AND** `timer_master_outputs` with at least 6 rows
- **AND** `pwm_alignment_options` with at least 4 rows

#### Scenario: timer_mode_flags reflects per-peripheral field presence

- **WHEN** the stm32-tier extractor processes a TIM1 peripheral
  with `register:tim1:rcr` present and `register:tim1:bdtr`
  carrying field `dtg`
- **THEN** the emitted `timer_mode_flags[*]` row for `TIM1` SHALL
  set `supports_repetition_counter = true`
- **AND** `supports_dead_time_insertion = true`

#### Scenario: unknown IP version falls back gracefully

- **WHEN** the stm32-tier extractor encounters a peripheral
  whose IP version has no registered mapping table
- **THEN** the extractor SHALL skip that peripheral silently
  rather than raising
- **AND** the merge engine's warning channel SHALL surface a
  single line per skipped IP version naming the missing
  mapping

### Requirement: The stm32-cubemx extractor SHALL surface ADC internal channels

The `stm32-cubemx` extractor SHALL detect internal-channel
pins in the MCU XML — `<Pin Name="VrefInt|TempSensor|VBat">`
with a child `<Signal Name="ADC{n}_IN_*">` — and SHALL project
them onto an `adc_internal_channels[]` payload field with
`(peripheral, channel_index, kind)` rows.  The `kind` field
SHALL take one of `temperature_sensor`, `vrefint`, `vbat`.

#### Scenario: STM32F407 surfaces three internal ADC channels

- **WHEN** the stm32-cubemx extractor processes `stm32f407vg`
- **THEN** the resulting payload's `adc_internal_channels`
  SHALL contain at least one row each with kinds
  `temperature_sensor`, `vrefint`, and `vbat`
- **AND** each row's `peripheral` field SHALL be `"ADC1"` and
  `channel_index` SHALL be a non-negative integer

### Requirement: A new stm32-cmsis-headers extractor SHALL parse calibration ROM constants

The `stm32-cmsis-headers` extractor SHALL parse the per-chip
`stm32<part>xx.h` header from
`STMicroelectronics/cmsis_device_<family>` repositories and
SHALL project the temperature-sensor + Vref-internal
calibration constants (`TEMPSENSOR_CAL[12]_ADDR`,
`TEMPSENSOR_CAL[12]_TEMP`, `VREFINT_CAL_ADDR`,
`VREFINT_CAL_VREF`) onto `adc_calibration_data_points[]` and
`adc_calibration_context`.  The extractor SHALL register one
source-pin entry per supported family
(`stm32-cmsis-device-g0`, `…-f4`, `…-l4`, `…-g4`, `…-h7`,
`…-u5`).

#### Scenario: stm32g071 calibration constants reach the canonical payload

- **WHEN** the stm32-cmsis-headers extractor processes
  `stm32g071rb` with the `stm32g071xx.h` header staged
- **THEN** the resulting payload's
  `adc_calibration_data_points` SHALL contain at least 3 rows
  (`vrefint_cal`, `ts_cal_low`, `ts_cal_high`)
- **AND** each row's `address` SHALL match the constant
  declared in the header (e.g. 0x1FFF75AA for VREFINT_CAL_ADDR)
- **AND** `adc_calibration_context.vrefint_nominal_mv` SHALL
  equal `VREFINT_CAL_VREF` from the header

### Requirement: A family-overlay TOML SHALL carry only constants nothing upstream structures

Each STM32 family SHALL have a
`data/vendors/st/<family>/family.toml` carrying ONLY the
constants no upstream source (SVD / CubeMX / CMSIS headers /
modm) provides — `i2c.speed_options`, `i2c.max_clock_hz`,
`adc.max_clock_hz`, `uart.max_baud_hz`,
`system_clock.post_reset_profile`.  Per-device overrides MAY
land at `data/vendors/st/<family>/devices/<device>.toml`.  The
overlay extractor `stm32-overlay` SHALL register as a
secondary EnrichmentExtractor and SHALL stamp every emitted
row's provenance with `source_id="stm32-overlay"` plus the
TOML's relative path.

#### Scenario: stm32g0 family overlay covers I2C + ADC max clocks

- **WHEN** the stm32-overlay extractor processes any
  `stm32g0*` device with `data/vendors/st/stm32g0/family.toml`
  present
- **THEN** the resulting payload SHALL carry `i2c_speed_options`
  with the 3 universal speeds (100k / 400k / 1M)
- **AND** `adc_max_clock_hz` SHALL equal the family's RM-cited
  max ADC clock
- **AND** `system_clock_profiles` SHALL contain at least the
  post-reset profile entry

#### Scenario: per-device override wins over family default

- **WHEN** `data/vendors/st/stm32g0/devices/stm32g030f6.toml`
  declares an `adc.max_clock_hz` value different from the
  family default
- **THEN** the stm32-overlay extractor's emitted payload for
  stm32g030f6 SHALL use the per-device value
- **AND** the family.toml value SHALL still apply to other
  stm32g0 chips

### Requirement: I2C timing presets SHALL be computed from speed × source-clock pairs

The `stm32_i2c_timing` helper SHALL implement the ST RM
TIMINGR formula and SHALL produce one
`i2c_timing_presets[]` row for each
(`i2c.speed_options[*]`, `system_clock_profiles[*].sysclk_hz`)
pair.  Each row SHALL carry the computed
`(presc, scldel, sdadel, sclh, scll)` plus the
(speed_hz, source_clock_hz) it was computed for.

#### Scenario: stm32g071rb I2C timing matches ST AN4235

- **WHEN** the i2c-timing helper computes a preset for
  `(speed_hz=100_000, source_clock_hz=64_000_000)`
- **THEN** the resulting `(presc, scldel, sdadel, sclh, scll)`
  tuple SHALL match the row published in ST application note
  AN4235 within rounding tolerance
- **AND** the same call repeated SHALL return a byte-identical
  tuple (determinism)

### Requirement: STM32 YAMLs re-emitted via this pipeline SHALL match canonical tier coverage

The bulk re-emit pipeline SHALL produce YAMLs carrying every tier-2/3/4 field already present in the `stm32g071rb` reference YAML — namely
`adc_resolution_options`, `adc_sample_time_options`,
`adc_oversampling_options`, `adc_internal_channels`,
`adc_calibration_data_points`, `adc_calibration_context`,
`adc_external_triggers`, `uart_data_bits_options`,
`uart_parity_options`, `uart_stop_bits_options`,
`spi_baud_prescaler_options`, `timer_prescaler_options`,
`timer_trigger_sources`, `timer_master_outputs`,
`timer_mode_flags`, `pwm_alignment_options`,
`pwm_break_inputs`, `pwm_deadtime_options`, `pwm_mode_flags`,
`i2c_speed_options`, `i2c_timing_presets`,
`peripheral_clock_bindings`, `system_clock_profiles`.
Every re-emitted YAML SHALL pass `validate_yaml_file` against
the bundled `device.schema.json`.

#### Scenario: stm32g030f6 lifts from 2/23 to 23/23 tier coverage

- **WHEN** the bulk pipeline re-emits `stm32g030f6` from
  upstream sources only (no hand-curated JSON)
- **THEN** the emitted YAML SHALL contain all 23 tier-2/3/4
  fields named in this requirement, populated with non-empty
  rows
- **AND** the emitted YAML SHALL pass schema validation

#### Scenario: re-emitted stm32g071rb stays close to canonical

- **WHEN** the bulk pipeline re-emits `stm32g071rb` and is
  diffed against the existing alloy-devices-yml YAML
- **THEN** every tier-2/3/4 field's row count SHALL match the
  canonical's count to within ±5 rows
- **AND** every divergence SHALL be documented in the
  drift report — either as a known difference (the upstream
  enum publishes more rows than the hand-curated JSON kept) or
  flagged as a regression to investigate before archive
