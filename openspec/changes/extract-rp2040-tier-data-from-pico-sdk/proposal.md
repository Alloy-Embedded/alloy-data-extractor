# Extract RP2040 Tier 2/3/4 Data from pico-sdk

## Why

The RP2040 YAMLs (pico, rp2040) ship with **3/6 peripheral
classes covered by tier 2/3/4 data**: UART/SPI/ADC are
populated, but **I2C, PWM, and Timer tier fields are empty**.
RP2040 has 22 peripherals and 153 registers — register-level
coverage is fine.  What's missing is the per-class
configuration knobs:

* I2C — supported speed modes (100k / 400k / 1M), timing
  presets per source-clock frequency.
* PWM — alignment options (edge / center-aligned), max
  prescaler, fractional-divider range, dead-time options.
* Timer — prescaler options, trigger sources, master output
  modes.

Result: the alloy HAL's `requires ValidI2cSpeed<I2C0, 1'000'000>`
concept can't validate against the chip's actual capability;
PWM trait emits zero-length `kSupportedAlignments` array.

The pico-sdk already has the data:

* `src/rp2_common/hardware_i2c/i2c.c` — `i2c_init()` carries the
  speed-mode table.
* `src/rp2_common/hardware_pwm/include/hardware/pwm.h` —
  fractional-divider min/max + alignment enum.
* `src/rp2_common/hardware_timer/include/hardware/timer.h` —
  alarm count + per-alarm DREQ.
* `src/rp2_common/hardware_clocks/clocks.c` — the
  fractional-divider range + valid source-clock set.

This change extends the existing `rp2040` extractor in
alloy-data-extractor to walk those headers and project the
data onto the canonical IR's tier fields.

## What Changes

- Extend `alloy_data_extractor.extractors.rp2040` with three
  new helpers:
  - `parse_i2c_tier(pico_sdk_root) -> I2cTierData` (speed_modes
    + timing_presets)
  - `parse_pwm_tier(pico_sdk_root) -> PwmTierData` (alignment +
    max_prescaler + max_period + supports_combined)
  - `parse_timer_tier(pico_sdk_root) -> TimerTierData`
    (alarm_count + per-alarm DREQ).  RP2040 timer is simpler
    than ARM advanced timers — no master output modes; just
    `supports_dma_burst` for the alarm DREQs.
- Project the parsed data onto the canonical IR's tier fields:
  - `device.i2c_speed_options`,
    `device.i2c_timing_presets`,
    `device.i2c_mode_flags`
  - `device.pwm_alignment_options`,
    `device.pwm_deadtime_options`,
    `device.pwm_break_inputs`,
    `device.pwm_mode_flags`
  - `device.timer_prescaler_options`,
    `device.timer_trigger_sources`,
    `device.timer_master_outputs`,
    `device.timer_mode_flags`
- Re-extract YAMLs for `pico` and `rp2040`.
- Expected delta per device:
  - i2c_speed_options: 0 → 3 (100k, 400k, 1M)
  - pwm_alignment_options: 0 → 2 (edge, center-aligned)
  - timer_master_outputs: 0 → 4 (one per alarm)

## Impact

Lifts pico + rp2040 from Grade C ("3/6 tier classes") to
Grade B ("6/6 tier classes covered").

After this lands, the alloy HAL's compile-time concepts
(`ValidI2cSpeed<I2C0, 400'000>`, `requires
PwmSemanticTraits<PWM0>::kHasCenterAligned`, etc) actually
have data to enforce on RP2040 targets.

## What this DOES NOT do

- Does not handle RP2350.  pico-sdk 2.x ships RP2350 too but
  the chip has different PWM (fractional divider extended) +
  timer (more alarms).  Admitting RP2350 is a separate
  `add-rp2350-target`-shaped change in alloy-codegen.
- Does not change the canonical IR schema.  Every field
  consumed already exists on `CanonicalDeviceIR`.
- Does not bake PIO instruction-set data — that has its own
  emitter (`runtime_driver_pio_semantics_header`) and a
  separate extraction path.
