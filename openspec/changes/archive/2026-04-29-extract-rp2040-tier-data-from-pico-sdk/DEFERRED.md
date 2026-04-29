# DEFERRED — pico-sdk cache only carries hardware_regs slice + IR coordination

## Why this archives without implementation

The proposal references three pico-sdk source files that the
local cache doesn't include:

- `src/rp2_common/hardware_i2c/i2c.c` — speed-mode whitelist for
  `i2c_init()`.
- `src/rp2_common/hardware_pwm/include/hardware/pwm.h` —
  `PWM_DIV_INT_MIN/MAX` and `pwm_chan_level_t` enum.
- `src/rp2_common/hardware_timer/include/hardware/timer.h` —
  alarm count + per-alarm DREQ.

The cache at
`alloy-codegen/.cache/sources/pico-sdk/src/` carries only
`rp2040/hardware_regs/include/hardware/regs/` — register-definition
headers.  The `rp2_common/hardware_*/` source tree, where the
high-level peripheral configuration lives, is not pinned.

Even with the source files staged, the same canonical-IR
coordination caveat that blocks `extract-tier-2-3-4-data-from-modm`
applies: the canonical YAML schema (`device.schema.json`) has no
`i2c_speed_options` / `pwm_alignment_options` / `timer_master_outputs`
top-level fields.  Adding them needs either an additive schema
bump or an agreed-upon sub-shape under `capabilities`.

The OpenSpec's task list is helpful even when blocked — many of
the values it asks the parser to "synthesise" are universal
constants the maintainer can hand-curate when the IR
coordination lands:

* I2C speed modes: 100k / 400k / 1M (standard / fast / fast_plus).
* PWM alignment modes: edge + center-aligned.
* PWM `supports_combined_pwm = True` etc. (per task 2.4).

## What's needed before this can land

- A pinned pico-sdk SHA carrying the `rp2_common/hardware_*/`
  tree, *or* an agreement to hand-curate the values per the
  OpenSpec's explicit constants.
- Either a schema bump for tier fields or agreement on a
  `capabilities` sub-shape (see the parallel deferral note in
  `2026-04-29-extract-tier-2-3-4-data-from-modm`).
- A test fixture covering at least one representative
  source-clock frequency for `i2c_timing_presets` computation.

## Where to look next

* `extractors/rp2040.py` — current rp2040 surface.
* `data/source_pins.toml::raspberrypi-pico-sdk` — pin entry that
  would need bumping to a SHA covering the `hardware_*/` tree.
