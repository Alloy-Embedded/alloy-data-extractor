# STM32 Tier-1/2/3/4 Pipeline

`complete-stm32-tier-coverage` (Phases 1-7).  How an STM32 chip
goes from upstream sources to a tier-2/3/4-complete canonical
YAML in `alloy-devices-yml`, with no hand-curated JSON
intermediate.

## Pipeline overview

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  CMSIS-SVD                STM32CubeMX            family.toml │
│  (cmsis-svd-data)         (db/mcu/*.xml)         (per-vendor)│
│       │                        │                       │     │
│       ▼                        ▼                       │     │
│  ┌──────────┐            ┌─────────────┐               │     │
│  │ stm32    │ primary    │ stm32-cubemx│ secondary    │     │
│  │ extractor│            │ extractor   │ enrichment   │     │
│  └─────┬────┘            └──────┬──────┘               │     │
│        │                        │                       │     │
│        │  ┌────────────────┐    │                       │     │
│        ├──│ register tree  │    │                       │     │
│        │  │ + enumValues   │    │                       │     │
│        │  └────────────────┘    │                       │     │
│        │                        │                       │     │
│        │                        │  ┌─────────────┐      │     │
│        │                        ├──│ stm32-tier  │ ←────┘     │
│        │                        │  │ projector   │            │
│        │                        │  └──────┬──────┘            │
│        │                        │         │                   │
│        │                        │         │  ┌──────────────┐ │
│        │                        │         │  │ stm32-overlay│ │
│        │                        │         │  │ + I2C TIMINGR│ │
│        │                        │         │  └──────┬───────┘ │
│        │                        │         │         │         │
│        ▼                        ▼         ▼         ▼         │
│       ┌─────────────────────────────────────────────────────┐│
│       │      merge_payloads (STM32_MERGE_POLICY)            ││
│       │      ───────────────────────────────                ││
│       │      schema 1.4.0 with field_provenance             ││
│       └────────────────────────┬─────────────────────────────┘│
│                                │                              │
│                                ▼                              │
│                     ┌────────────────────┐                    │
│                     │ write_device_yaml  │                    │
│                     └─────────┬──────────┘                    │
│                               │                               │
│                               ▼                               │
│        alloy-devices-yml/vendors/st/<family>/devices/*.yml    │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

## Field-ownership table

Which extractor produces which canonical YAML field.

| Canonical field | Extractor | Source | Phase |
|---|---|---|---|
| `peripherals` | `stm32` | CMSIS-SVD `<peripherals>` | Pre-existing |
| `interrupts` | `stm32` | CMSIS-SVD `<interrupt>` | Pre-existing |
| `registers` | `stm32` (via cmsis-svd) | SVD register tree | `18fd166` |
| `register_fields` | `stm32` | SVD `<field>` blocks | `18fd166` |
| `register_field_enumerations` | `cmsis-svd` | SVD `<enumeratedValues>` | Phase 1 (`777f429`) |
| `pins` | `stm32-cubemx` | CubeMX MCU XML `<Pin>`/`<Signal>` | Existing |
| `dma_requests` | `stm32-cubemx` | CubeMX DMA IP XML | Existing |
| `clock_nodes`, `clock_selectors` | `stm32-cubemx` | CubeMX clocktree plugin XML | Existing |
| `cubemx_peripherals` | `stm32-cubemx` | CubeMX `<IP>` per-instance metadata | Phase 2 (`3c413ca`) |
| `adc_resolution_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `adc_sample_time_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `adc_oversampling_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `adc_external_triggers` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `uart_data_bits_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `uart_parity_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `uart_stop_bits_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `uart_mode_flags` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `spi_baud_prescaler_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `i2c_mode_flags` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `timer_prescaler_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `timer_trigger_sources` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `timer_master_outputs` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `timer_mode_flags` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `pwm_alignment_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `pwm_break_inputs` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `pwm_deadtime_options` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `pwm_mode_flags` | `stm32-tier` | per-IP-version mapping table | Phase 2 |
| `adc_internal_channels` | `stm32-overlay` | family.toml `[[adc.internal_channels]]` | Phase 5 |
| `adc_calibration_data_points` | `stm32-overlay` | family.toml `[[adc.calibration_data_points]]` | Phase 5 |
| `adc_calibration_context` | `stm32-overlay` | family.toml `[adc.calibration_context]` | Phase 5 |
| `adc_max_clock_hz` | `stm32-overlay` | family.toml `adc.max_clock_hz` | Phase 5 |
| `uart_max_baud_hz` | `stm32-overlay` | family.toml `uart.max_baud_hz` | Phase 5 |
| `i2c_speed_options` | `stm32-overlay` | family.toml `[[i2c.speed_options]]` | Phase 5 |
| `i2c_max_clock_hz` | `stm32-overlay` | family.toml `i2c.max_clock_hz` | Phase 5 |
| `system_clock_profiles` | `stm32-overlay` | family.toml `[system_clock]` | Phase 5 |
| `i2c_timing_presets` | `stm32-overlay` | computed from speeds × sysclks (AN4235) | Phase 6 |

## Adding a new STM32 chip

For a chip in an already-supported family (e.g. another G0):

```bash
# 1. Stage the SVD (cmsis-svd-data already covers most ST chips).
# 2. Stage the CubeMX MCU XML (already in any CubeMX install).
# 3. No code changes needed.

PYTHONPATH=src python3 scripts/reemit_stm32_with_cubemx.py \
    --device stm32g0c1ce --family stm32g0 \
    --cmsis-svd-root <cmsis-svd-data> \
    --open-pin-data-root <STM32_open_pin_data> \
    --cubemx-db <STM32CubeMX-install>/db \
    --output-root /tmp/stm32g0c1ce-reemit
```

For a chip in a new family (e.g. STM32U5):

```toml
# data/vendors/st/stm32u5/family.toml
[adc]
max_clock_hz = ...

[adc.calibration_context]
peripheral = "ADC1"
vrefint_nominal_mv = ...
...

[uart]
max_baud_hz = ...

[i2c]
max_clock_hz = ...
[[i2c.speed_options]]
name = "standard"
speed_hz = 100_000
...

[system_clock.post_reset_profile]
name = "default-msi-4mhz"
sysclk_hz = 4_000_000
...
```

If the new family uses a different IP version (e.g. `usart3_v1_x_Cube`),
add a `TierMapping` entry to
`extractors/stm32_tier_mappings.py`.  Most G4/L4/H7/U5 chips
share IP versions with G0/F4 and need no new mapping.

## Bulk re-emit

The `scripts/reemit_stm32_with_full_tier.py` driver runs the
full pipeline for every admitted ST device:

```bash
PYTHONPATH=src python3 scripts/reemit_stm32_with_full_tier.py \
    --cmsis-svd-root <cmsis-svd-data> \
    --open-pin-data-root <STM32_open_pin_data> \
    --cubemx-db <STM32CubeMX-install>/db \
    --canonical-root <alloy-devices-yml> \
    --output-root /tmp/stm32-bulk-reemit
```

Outputs:

* `bulk-tier-report.json` — per-chip line counts, tier-field
  coverage, drift counts vs the canonical YAML.
* `bulk-tier-report.md` — same data as a Markdown table.

## Tier coverage achieved

Last run against the 5 admitted ST devices:

| Device | Tier fields | Canonical (before) | Re-emit lines | Canonical lines |
|---|---|---|---|---|
| stm32f401re | 21/22 | 12/22 | 63,835 | 75,307 |
| stm32f405rg | 21/22 | 12/22 | 167,478 | 195,254 |
| stm32g030f6 | 22/22 | 2/22 | 55,225 | 52,478 |
| stm32g071rb | 22/22 | 23/22 | 67,134 | 73,410 |
| stm32g0b1re | 22/22 | 15/22 | 165,239 | 94,231 |

* F4 chips score 21/22 because STM32F4 silicon lacks
  ADC oversampling (hardware fact, not a missing mapping).
* `stm32g030f6` jumped from Grade D (2/22) to Grade A (22/22) —
  the biggest single-device fix in this OpenSpec.
