# Complete STM32 Tier 2/3/4 Coverage from Upstream Sources

## Why

The 5 admitted STM32 chips in alloy-devices-yml carry wildly
inconsistent tier-2/3/4 coverage — the data the alloy-codegen
runtime traits consume to emit non-stub C++ headers:

| Chip | Tier-2/3/4 fields populated | Status |
|---|---|---|
| stm32g071rb | 23/23 | ✅ reference |
| stm32g0b1re | 15/23 | partial |
| stm32f401re | 12/23 | thin (no timer/PWM) |
| stm32f405rg | 12/23 | thin |
| stm32g030f6 | 2/23 | empty |

The existing fully populated YAMLs (g071rb especially) carry
that data because alloy-codegen's previous pipeline ran a
**bootstrap-patch overlay** sourced from hand-curated JSON
files in the sibling `alloy-devices/` repo
(`alloy-devices/st/<family>/metadata/devices/<device>.json`,
e.g. 5,659–267,489 lines per chip).

Those JSONs are not a viable foundation:

* They were **hand-curated** for a small set of chips (the 5
  admitted devices); they don't exist for stm32g030f6 or
  stm32g0b1re — exactly the chips with the worst YAMLs today.
* New STM32 chips have no JSON, so no canonical YAML can be
  emitted for them through the bootstrap-patch path.
* The data they contain is largely **already published** by ST
  in upstream sources (CMSIS-SVD `<enumeratedValues>`, CubeMX
  MCU XML internal-channel signals, CMSIS device headers like
  `stm32g0xx.h`).  Curating it by hand was a workaround, not a
  long-term plan.

This change ports those tier-2/3/4 sources into
alloy-data-extractor as deterministic upstream-driven
extractors, so any STM32 chip with an SVD + CubeMX entry +
CMSIS device header gets full tier coverage with zero
hand-curation.

## What Changes

A 6-phase pipeline composed via the existing merge engine:

### Phase 1 — Extract `<enumeratedValues>` from CMSIS-SVD

Extend `cmsis_svd._register_and_field_records` to emit a new
`register_field_enumerations` array on every payload.  Each
row carries `(field_id, name, raw_value, description)` projected
straight from SVD's `<field><enumeratedValues><enumeratedValue>`
blocks.  Universal change benefiting every vendor whose SVD
ships enumerated values (ST/Nordic/NXP/RP2040/Espressif).

### Phase 2 — `stm32-tier` projector (secondary extractor)

New secondary extractor that reads `register_field_enumerations`
+ peripheral CubeMX IP versions, then projects them onto the
canonical tier arrays via per-IP-version mapping tables:

* `field:adc{n}:cfgr1:res` → `adc_resolution_options`
* `field:adc{n}:smpr1:smp{ch}` → `adc_sample_time_options`
* `field:adc{n}:cfgr2:ovsr` → `adc_oversampling_options`
* `field:adc{n}:cfgr1:extsel` → `adc_external_triggers`
* `field:usart{n}:cr1:m0` + `m1` → `uart_data_bits_options`
* `field:usart{n}:cr1:pce/ps` → `uart_parity_options`
* `field:usart{n}:cr2:stop` → `uart_stop_bits_options`
* `field:rcc:ccipr:usart{n}sel` → `uart_baud_clock_sources`
* `field:spi{n}:cr1:br` → `spi_baud_prescaler_options`
* `field:tim{n}:smcr:ts` → `timer_trigger_sources`
* `field:tim{n}:cr2:mms` → `timer_master_outputs`
* `field:tim{n}:cr1:cms` → `pwm_alignment_options`

Plus computed-from-field-shape projections:

* `timer_prescaler_options` ← `[1, 2, …, 2**TIM.PSC.bit_width]`
* `pwm_deadtime_options` ← `[0, …, 2**TIM.BDTR.DTG.bit_width]`
* `timer_mode_flags` ← field-presence detection (peripheral has
  `CR1.RCR` ⇒ `supports_repetition_counter`)
* `pwm_break_inputs` ← peripherals carrying BDTR.BKE / BK2E

Mapping tables are keyed by **IP version** (`usart_v3_1`,
`adc_v3_0`, `gptimer_v3_x_Cube`, etc.) — discovered via the
`stm32-cubemx` extractor's `<IP Version="...">` capture.
Adding a new IP version is 20-50 lines of mapping table per
peripheral class.

### Phase 3 — Extend `stm32-cubemx` for ADC internal channels

Extend the CubeMX MCU XML walker to detect:

* `<Pin Name="VrefInt"><Signal Name="ADC1_IN_Vrefint"/></Pin>`
* `<Pin Name="TempSensor"><Signal Name="ADC1_IN_TempSens"/></Pin>`
* `<Pin Name="VBat"><Signal Name="ADC1_IN_Vbat"/></Pin>`

Project as `adc_internal_channels[]` rows with kind ∈
{`temperature_sensor`, `vrefint`, `vbat`} and the correct
`channel_index` (parsed from the signal-name suffix).

### Phase 4 — New extractor `stm32-cmsis-headers`

New primary extractor parsing `stm32<series>xx.h` from the
official `STMicroelectronics/cmsis_device_<family>` repos
(`cmsis_device_g0`, `cmsis_device_f4`, …).  Captures:

```c
#define TEMPSENSOR_CAL1_ADDR  ((uint16_t*)(0x1FFF75A8UL))
#define TEMPSENSOR_CAL2_ADDR  ((uint16_t*)(0x1FFF75CAUL))
#define TEMPSENSOR_CAL1_TEMP  (30)
#define TEMPSENSOR_CAL2_TEMP  (130)
#define VREFINT_CAL_ADDR      ((uint16_t*)(0x1FFF75AAUL))
#define VREFINT_CAL_VREF      (3000)
```

Projects as:

* `adc_calibration_data_points[]` rows with `(kind, address,
  size_bits, peripheral, semantic_constant)`
* `adc_calibration_context` — fills `vrefint_nominal_mv`,
  `cal_temp_low_celsius`, `cal_temp_high_celsius`,
  `cal_voltage_mv`

Pin entry per family in `data/source_pins.toml`:
`stm32-cmsis-device-<family> @ <git-sha>`.

### Phase 5 — Family overlay TOMLs (truly hand-curated only)

Per-family TOML in `data/vendors/st/<family>/family.toml`
carrying ONLY the constants nothing upstream structures:

* `i2c.speed_options` (universal: 100k/400k/1M)
* `i2c.max_clock_hz` (RM-table per family)
* `adc.max_clock_hz` (RM-table per family)
* `uart.max_baud_hz` (RM-table per family)
* `system_clock.post_reset_profile` (post-reset state — universal
  per family, e.g. STM32G0 boots HSI 16 MHz)

Expected size: ~50-80 lines per family TOML.  Compare to the
existing hand-curated JSON files (5k-267k lines per **chip**)
— this is two orders of magnitude smaller because the bulk now
comes from upstream extractors.

### Phase 6 — Compute `i2c_timing_presets` deterministically

Helper computing `(presc, scldel, sdadel, sclh, scll)` from the
RM TIMINGR formula given a target speed (Phase 5) and source
clock frequency (already in `system_clock_profiles`).  No new
data — pure derivation.

### Phase 7 — Bulk re-emit + verification

Pipeline composed via `STM32_MERGE_POLICY`:

```
SVD primary (registers + fields + enums)
  ⊕ stm32-cubemx (pinmux + DMA + clock + ADC channels)
  ⊕ stm32-cmsis-headers (calibration ROM)
  ⊕ stm32-tier (enum projection → tier arrays)
  ⊕ stm32-overlay (family TOML constants)
  → merge → schema-validate → write canonical YAML
```

Re-emit YAMLs for the 5 admitted STM32 chips through this
pipeline.  Verify each YAML carries ≥ the same 23 tier-2/3/4
fields the existing g071rb does, with values matching the
hand-curated JSONs to within documented small differences (RM
PDF tables vs SVD enum names).

## Impact

* alloy-data-extractor: +~1,200 LOC (Phases 1-6 implementations)
  + ~360 lines of TOML overlays (5-6 STM32 families × ~60
  lines).  All 5 admitted ST chips reach tier parity with each
  other.  Adding a new ST chip in an already-supported family
  becomes "stage SVD + CubeMX entry; run bulk extract" — no new
  Python or TOML.
* alloy-devices-yml: 5 STM32 YAMLs regenerated (g071rb expected
  byte-near-identical; the other 4 grow significantly).
* alloy-codegen: no changes; the canonical YAMLs already carry
  the tier-2/3/4 fields and the runtime trait builders already
  consume them.  This change drops the bootstrap-patch
  dependency by sourcing the same data from upstream.

Phase 1 (`<enumeratedValues>` in cmsis_svd) is an
**universal** improvement — Nordic, NXP, RP2040, and Espressif
SVDs also publish enumerated values that follow-up changes can
project for those vendors.

## What this does NOT do

* Does not extend tier coverage to non-STM32 vendors.  Each
  vendor needs its own tier projector wired against its own
  IP-version vocabulary; STM32 is the first.
* Does not admit new STM32 chips.  Bulk admission stays a
  separate, parallel workstream.
* Does not handle CAN / USB / Ethernet / QSPI / SDMMC / RTC /
  Watchdog tier data — those peripheral classes are still stubs
  in alloy-codegen (`populate-tier1-stub-driver-semantics`) and
  need their own descriptor schema before extraction makes
  sense.
* Does not migrate the existing ST hand-curated JSONs in
  `alloy-devices/`; those stay as a reference for verifying the
  re-emitted YAMLs but are no longer load-bearing.
* Does not change the canonical YAML schema; every field the
  pipeline produces already has a slot in
  `device.schema.json` / `CanonicalDeviceIR`.
