# Extract Tier 2/3/4 Data from modm-devices

## Why

The canonical YAMLs for STM32F4 / STM32G0 carry ADC + UART +
SPI + I2C tier-2/3/4 data (data-bits options, parity, baud
clock sources, ADC sample-time options, etc.) but the **Timer**
tier is empty for every STM32 except `stm32g071rb` — that one
was hand-curated in the codegen patches before the
canonical-YAML pivot.  Result: every Timer trait in the
emitted C++ ships with `std::array<uint8_t, 0> kTriggerSources
= {};` and `kSupportsRepetitionCounter = false`.

modm-devices already carries the missing facts:

* `<driver name="timer">` blocks list `prescaler`,
  `auto_reload_max`, every `<trigger>` (ITR0..ITRn, TI1F_ED,
  TI2FP2, ETRF, …), every `<master_output>` mode (Reset /
  Update / OC1Ref / …), and the `repetition_counter` /
  `dma_burst` / `xor_input` capability flags.
* The same data drives modm's own peripheral configuration so
  it's authoritative.

Re-using modm-devices lets us turn 4 STM32 devices from
"Timer trait stub" to "fully populated" without a new vendor
scrape.

## What Changes

- Extend `alloy_data_extractor.extractors.modm_devices` with a
  `parse_timer_tier_data(timer_block)` step that mirrors the
  existing UART / SPI / ADC tier helpers.
- Project the parsed data onto the canonical IR's six STM32
  tier fields:
  - `device.timer_prescaler_options`
  - `device.timer_trigger_sources`
  - `device.timer_master_outputs`
  - `device.timer_mode_flags` (`supports_dma_burst`,
    `supports_repetition_counter`, `supports_xor_input`)
  - `device.pwm_alignment_options` (Edge / Center-1 / Center-2 /
    Center-3 — already in the modm `pwm` block)
  - `device.pwm_break_inputs`
- Re-emit YAML for all 6 admitted STM32 devices through the
  pipeline (`alloy-data-extractor extract --vendor st`).
- Expected per-device deltas (timer trait completeness):
  - stm32f401re: 0 → 8 trigger sources + 8 master outputs
  - stm32f405rg: 0 → 8 trigger sources + 8 master outputs
  - stm32g030f6: 0 → 4 trigger sources + 6 master outputs
  - stm32g0b1re: 0 → 8 trigger sources + 8 master outputs
  - stm32g071rb: stays full (regression check only)

## Impact

After this lands and the YAMLs ship in alloy-devices-yml, the
emitted `timer.hpp` for STM32G0/F4 carries the full ITR matrix
+ master-output (MMS) array + capability flags.  The PWM
emitter gains `kSupportedAlignments` and `kBreakInputs` arrays
populated from real silicon data.

Lift roughly 4 of the 9 "Timer tier missing" devices out of
the C bucket and into B (per the alloy-devices-yml audit).
Same-day fix; no new dependencies.

## What this DOES NOT do

- Does not extend tier coverage to Espressif / NXP / Nordic /
  RP2040.  modm-devices is STM32 + AVR + (some) Sam-D.  Those
  vendors get their own follow-up changes
  (`extract-rp2040-tier-data-from-pico-sdk`,
  `extract-espressif-tier-data-from-soc`, etc).
- Does not add new tier *fields* to the canonical IR.  All
  fields consumed already exist on `CanonicalDeviceIR`; this
  change just populates them.
- Does not handle the AVR-DA Timer/Counter-A — that goes
  through Microchip ATDF, not modm.
