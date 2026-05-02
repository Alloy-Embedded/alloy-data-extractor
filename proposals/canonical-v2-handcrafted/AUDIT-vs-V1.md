# Audit — what canonical-v2 (hand-crafted) lost vs canonical-v1 (auto)

Compared each v2 YAML against the closest admitted v1 chip in
alloy-devices-yml.  Three of the five have direct equivalents
(`esp32`, `nrf52840`, `rp2040`); STM32F103 and ATmega328P used
the closest cousin (`stm32g030f6`, `avr128da32`).

For each top-level section v1 carries, this table classifies whether
v2 covers it and, if not, whether the loss matters for codegen.

| Legend | Meaning |
|--------|---------|
| ✅ | Covered in v2 (renamed / restructured but equivalent) |
| 🟡 | Partial — v2 has the concept but loses some detail |
| ❌ | **Genuinely lost** — codegen needs it; v2 must restore |
| ⚪ | Synthesis output of alloy-codegen (empty in raw v1 YAMLs); v2 doesn't need it |

## Section-by-section verdict

### Identity / memory / packages / pins

| v1 section            | v2 mapping                                  | Verdict |
|-----------------------|---------------------------------------------|---------|
| `schema_version`      | `schema:`                                   | ✅      |
| `identity`            | `identity:`                                 | ✅      |
| `provenance`          | `provenance:`                               | ✅      |
| `provenance_defaults` | top-level `provenance:` (single block)      | ✅      |
| `memories`            | `memory:` (+ `address_space`, `backing`)    | ✅ improved |
| `packages`            | implied by `pinout` + `identity.package`    | ✅      |
| `package_pads`        | merged into `pinout[].pin/pad/signal/role`  | ✅      |
| `pins`                | `pinout`                                    | ✅      |
| `pin_constraints`     | (none)                                      | ❌ **LOST** |

### Peripherals / interrupts

| v1 section                | v2 mapping                              | Verdict |
|---------------------------|-----------------------------------------|---------|
| `ip_blocks`               | `templates:` + `peripherals[].template` | ✅ improved |
| `peripherals`             | `peripherals:`                          | ✅      |
| `interrupts`              | `interrupts:`                           | ✅      |
| `cubemx_peripherals`      | (none — only ST has this)               | ❌ **LOST** (need IP version) |
| `peripheral_clock_bindings` | `peripherals[].rcc.en/rst`            | ✅      |

### Registers (the big one)

| v1 section                  | v2 mapping                              | Verdict |
|-----------------------------|-----------------------------------------|---------|
| `registers`                 | `templates.<ip>.registers`              | 🟡 partial — v2 has only the registers codegen reads |
| `register_fields`           | `templates.<ip>.fields`                 | 🟡 partial — v2 has only the bits codegen flips |
| `register_field_enumerations` | (none)                                | ❌ **LOST** — enum values per field |

### Clock tree

| v1 section              | v2 mapping                                 | Verdict |
|-------------------------|--------------------------------------------|---------|
| `clock_nodes`           | `clock.domains[]`                          | 🟡 — loses clock-tree topology graph |
| `clock_selectors`       | implicit in `clock.domains[].sources`      | 🟡 — loses register-target mapping |
| `system_clock_profiles` | `clock.reset_state` + `system_examples`    | 🟡 — loses recommended profiles |

### DMA

| v1 section            | v2 mapping                                  | Verdict |
|-----------------------|---------------------------------------------|---------|
| `dma_controllers`     | `peripherals[].template: dma_controller`    | ✅      |
| `dma_requests`        | `peripherals[].dma.tx.dreq`                 | 🟡 — request matrix can also live as a top-level table for sharing |

### Tier-2/3/4 (peripheral options)

| v1 section                          | v2 mapping                              | Verdict |
|-------------------------------------|-----------------------------------------|---------|
| `adc_resolution_options`            | `templates.adc.options.resolution`      | ✅      |
| `adc_sample_time_options`           | `templates.adc.options.sample_time_cycles` | ✅   |
| `adc_oversampling_options`          | `templates.adc.options.oversampling`    | ✅      |
| `adc_internal_channels`             | `peripherals[adc1].channels.{ch16: temp_sensor}` | 🟡 — chan number embedded; misses STM32 calibration cross-ref |
| `adc_calibration_data_points`       | (none)                                  | ❌ **LOST** — TS_CAL1/2 ROM addresses |
| `adc_calibration_context`           | (none)                                  | ❌ **LOST** — vrefint nominal mV, cal temp range |
| `adc_external_triggers`             | (none)                                  | ❌ **LOST** — EXTSEL field values per timer source |
| `adc_max_clock_hz`                  | `templates.adc.max_clock`               | ✅      |
| `uart_*`                            | `templates.uart.options.*`              | ✅      |
| `uart_max_baud_hz`                  | `templates.uart.max_baud`               | ✅      |
| `spi_baud_prescaler_options`        | `templates.spi.options.baud_prescaler`  | ✅      |
| `spi_mode_flags` / `frame_size`     | `templates.spi.options.modes/data_size` | ✅      |
| `i2c_speed_options` / `mode_flags`  | `templates.i2c.options.speeds`          | ✅      |
| `i2c_timing_presets`                | (none)                                  | ❌ **LOST** — TIMINGR precomputed values |
| `i2c_max_clock_hz`                  | `templates.i2c.max_clock` (missing)     | 🟡 — easy add |
| `timer_trigger_sources`             | (none)                                  | ❌ **LOST** — slave-mode trigger field values |
| `timer_master_outputs`              | (none)                                  | ❌ **LOST** — TRGO MMS field values |
| `timer_prescaler_options`           | `templates.timer_general.options`       | ✅      |
| `timer_mode_flags`                  | `templates.timer_general.options`       | ✅      |
| `pwm_alignment_options`             | `templates.timer_general.options`       | ✅      |
| `pwm_break_inputs`                  | (none)                                  | ❌ **LOST** — break-input field values |
| `pwm_deadtime_options`              | (none)                                  | ❌ **LOST** — DTG prescaler/count tables |
| `pwm_mode_flags`                    | (none)                                  | 🟡 — mostly subsumed by capabilities |
| `peripheral_max_clock_hz`           | `templates.<ip>.max_clock`              | 🟡 — per-instance overrides missing |

### Vendor-specific runtime descriptors

| v1 section                    | v2 mapping                                  | Verdict |
|-------------------------------|---------------------------------------------|---------|
| `gpio_pins` (per-pin AF table)| `pinout[]` + `peripherals[].pin_options`    | ✅      |
| `i2c_peripherals`             | merged into template + per-instance         | ✅      |
| `mcpwm_peripherals` (esp)     | merged into template + per-instance         | ✅      |
| `rp2040_uart_peripherals`     | template + `dma.{tx,rx}.dreq` + valid pins  | ✅      |
| `rp2040_spi_peripherals`      | same                                        | ✅      |
| `rp2040_pwm_slice_hw`         | template + per-instance                     | ✅      |
| `rp2040_dma_controller_hw`    | template + per-instance                     | ✅      |
| `rp2040_timer_controller_hw`  | template + per-instance                     | ✅      |
| `avr_da_tca_pwm_peripherals`  | template + per-instance                     | ✅      |
| `usb_controllers`             | `peripherals[].template: usb`               | ✅      |
| `stm_timer_pwm_peripherals`   | template + per-instance                     | ✅      |
| `stm32_tier_resolution`       | (diagnostic only)                           | ⚪      |

### Synthesised by alloy-codegen (empty in raw v1 YAMLs)

| v1 section              | v2 mapping | Verdict |
|-------------------------|------------|---------|
| `interrupt_bindings`    | (codegen synthesises from `peripherals[].irq`) | ⚪ |
| `vector_slots`          | same                                            | ⚪ |
| `capabilities`          | same — derived from templates                   | ⚪ |
| `signal_endpoints`      | same                                            | ⚪ |
| `route_requirements`    | same                                            | ⚪ |
| `route_operations`      | same                                            | ⚪ |
| `connection_candidates` | same                                            | ⚪ |
| `connection_groups`     | same                                            | ⚪ |
| `dma_routes`            | same                                            | ⚪ |
| `dma_bindings`          | same                                            | ⚪ |
| `startup_descriptors`   | same                                            | ⚪ |

## What v2 genuinely lost (must restore)

These nine items are **real codegen-relevant data** that my hand-crafted v2
left out.  Most are STM32-specific because the v1 ST overlay is more
mature; the schema needs to accept them generically.

1. **`pin_constraints`** — `analog-only` flag on RP2040 GP26-29; voltage
   tolerance flags on STM32 5V-tolerant pins.  Codegen rejects digital
   config on analog-only pads.

2. **`register_field_enumerations`** — enum values for fields like
   `SPI.CR1.BR`, `ADC.CFGR1.RES`.  Without them codegen has to hardcode
   "0 = /2, 1 = /4, …" instead of name-keyed lookups.

3. **ADC calibration ROM** (`adc_calibration_data_points` + `_context`)
   — TS_CAL1 / TS_CAL2 / VREFINT_CAL ROM addresses + nominal voltages
   + cal temperature points.  Codegen needs them to convert raw ADC →
   °C / mV with vendor-promised accuracy.

4. **ADC external triggers** (`adc_external_triggers`) — EXTSEL field
   values per timer→ADC trigger source.  Required for triggered-conv
   codepath.

5. **I²C timing presets** (`i2c_timing_presets`) — precomputed TIMINGR
   register values per (target speed × source clock).  Saves codegen
   from running the AN4235 timing solver in C++ at compile time (the
   solver is non-trivial and version-dependent).

6. **Timer trigger sources** (`timer_trigger_sources`) — TIMx slave-
   mode trigger field values.  Needed for inter-timer synchronisation.

7. **Timer master outputs** (`timer_master_outputs`) — MMS field values
   for the TRGO output mux.  Same use-case.

8. **PWM break inputs + deadtime options** — STM32 advanced-timer
   features (TIM1, TIM8) with hardware-specific tables.

9. **CubeMX IP version** (`cubemx_peripherals[].ip_version`) — string
   like `aditf4_v3_0_G0_Cube` that selects the right alloy-codegen
   driver template variant.  v2 has `template:` but not the version
   subkey.

## What v2 partially lost (worth tightening)

10. **System-clock profiles**.  v1 ships named profiles
    (`safe-rc-fast-8mhz`, `pll-hsi16-64mhz`, `pll-hse-72mhz`) with full
    PLL multiplier tables.  v2's `clock.reset_state` only covers the
    boot state.  → add a `clock.profiles[]` list.

11. **Per-instance `max_clock_hz` overrides** — some peripherals run
    slower than the template max (e.g. STM32 USART2 capped at PCLK1).
    v2 should allow `peripherals[].max_clock` to override
    `templates.<ip>.max_clock`.

12. **Clock-selector register targets**.  v1 records
    `selector:clk-ref-src.register_target = CLOCKS_CLK_REF_CTRL.SRC`,
    which is what codegen writes to switch sources.  v2's
    `clock.domains[].sources` lists names but not the register field
    that picks among them.  → add `clock.domains[].select_register`.

13. **Register-fields catalogue completeness**.  My v2 templates list
    only the bits codegen flips at init.  But many emitters touch
    runtime-status / error / DMA-related bits too.  → either expand
    the template, or treat the template as an **opt-in subset** and
    keep a complete `register_fields[]` list reachable for bulk
    operations.

## What v2 added that v1 lacks

| v2 feature                          | Why it matters |
|-------------------------------------|----------------|
| `address_space` on memory regions   | AVR Harvard chips silently broke in v1 |
| `multicore` under `core`            | ESP32 + RP2040 dual-core formalised |
| `backing: external-qspi-flash`      | XIP boot stage 2 emitter knows what to generate |
| `mutex_group` on shared bases       | nRF52 SPIM/TWIM/UARTE conflict detection |
| Pin-mux family flag (matrix/psel)   | GPIO matrix vs fixed-AF dispatch in codegen |
| `templates:` IP block reuse         | 40-150× shrink on register-heavy chips |
| `system_examples:` golden snippets  | Built-in integration tests + reviewer docs |

## Recommended canonical-v2.1 deltas

Add these top-level keys / template extensions to fill the nine real
losses:

```yaml
# (1) per-pin constraints
pinout:
  - { signal: GP26, pico: GP26, adc: ch0, constraints: [analog-only] }
  - { signal: PA9,  ft: 5v_tolerant }                               # STM32

# (2) field enums in templates
templates:
  spi:
    fields:
      cr1.br:
        bits: [3, 5]
        enum: { div_2: 0, div_4: 1, div_8: 2, div_16: 3,
                div_32: 4, div_64: 5, div_128: 6, div_256: 7 }

# (3) ADC calibration ROM (under each ADC instance)
peripherals:
  - id: adc1
    template: adc
    calibration:
      vrefint:    { rom_addr: 0x1FFF75AA, size_bits: 16, nominal_mv: 3000 }
      ts_cal_low: { rom_addr: 0x1FFF75A8, size_bits: 16, temp_celsius: 30 }
      ts_cal_high:{ rom_addr: 0x1FFF75CA, size_bits: 16, temp_celsius: 130 }

# (4) ADC external triggers (per-instance)
    external_triggers:
      - { source: tim1_trgo2, extsel: 0, polarity: rising }
      - { source: tim1_cc4,   extsel: 1, polarity: rising }

# (5) I²C TIMINGR precomputed table
    timing_presets:
      - { speed: 100kHz, source_clock: 16MHz, timingr: 0x10310926 }
      - { speed: 400kHz, source_clock: 64MHz, timingr: 0x6000030D }

# (6) timer slave-mode triggers (template-level)
templates:
  timer_general:
    trigger_sources: { itr0: 0, itr1: 1, itr2: 2, itr3: 3, etrf: 7 }

# (7) timer master output (TRGO MMS) — template
    master_outputs: { reset: 0, enable: 1, update: 2, compare-pulse: 3,
                      compare-oc1ref: 4, compare-oc2ref: 5,
                      compare-oc3ref: 6, compare-oc4ref: 7 }

# (8) advanced-timer PWM features
templates:
  timer_advanced:                           # extends timer_general
    extends: timer_general
    capabilities_extra: [break-input, dead-time, complementary-output]
    break_inputs: [bkin, bkin2]
    deadtime_options:
      - { dtg_prescaler: 0, count_bits: 7, max_ns: 1270 }
      - { dtg_prescaler: 1, count_bits: 6, max_ns: 2540 }

# (9) CubeMX IP version sub-key
peripherals:
  - id: adc1
    template: adc
    ip_version: aditf4_v3_0_G0_Cube         # picks the right driver variant

# (10) clock profiles (top-level list under clock)
clock:
  profiles:
    - { id: post-reset,    source: hsi, sysclk: 8MHz, kind: post-reset }
    - { id: pll-hse-72mhz, source: pll_main, sysclk: 72MHz,
        pll: { input: hse, mul: 9 }, kind: recommended }

# (11) per-instance max_clock override
peripherals:
  - id: usart2
    template: usart
    max_clock_override: 36MHz                # PCLK1-bound on STM32F1

# (12) clock-selector register targets
clock:
  domains:
    - id: sysclk
      sources: [hsi, hse, pll_main]
      max: 72MHz
      select_register: { reg: RCC.CFGR, field: SW, encoding: { hsi: 0, hse: 1, pll_main: 2 } }
```

Net effect: v2.1 still ~500 lines per chip (cf. v1's 70 KB compacted /
3 MB raw), but no longer drops any codegen-relevant fact.  The nine
items above are bounded — adding them to the templates + per-instance
scopes is ~30-50 lines per chip extra, not another 70 KB.

## Do not restore

These v1 sections are **correctly dropped** in v2 and should stay out:

* `interrupt_bindings`, `vector_slots`, `capabilities`,
  `signal_endpoints`, `route_*`, `connection_*`, `dma_routes`,
  `dma_bindings`, `startup_descriptors`, `ip_blocks` — all empty in
  raw v1 YAMLs (alloy-codegen synthesises them from the raw fields
  during normalize).  v2 should rely on the same synthesis.
* `stm32_tier_resolution` — diagnostic listing of which IPs got tier
  mapping.  Belongs in CI output, not the canonical YAML.
* Per-row `provenance` blocks — v2's single top-level provenance is
  enough; per-row overrides are 1% case.
* All `register_*` / `peripheral` / `register_offset` echo fields on
  `route_operations` / `clock_gates` / `resets` — pure diagnostic
  duplicates of `register_id`.

## Verdict

The hand-crafted v2 dropped **9 codegen-relevant items** and partially
weakened **4 more**.  All 13 are recoverable by extending the existing
v2 schema (templates + per-instance overrides), with no architectural
change.  The other ~30 v1 sections are either covered by v2's
restructuring or are codegen synthesis output that doesn't belong in
the source-of-truth YAML.

Recommendation: lock in v2 as the target schema, add the v2.1 deltas
above, and have the auto-extractors converge on it.
