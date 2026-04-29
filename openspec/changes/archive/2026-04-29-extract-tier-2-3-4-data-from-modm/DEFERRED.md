# DEFERRED — modm-devices XML cache not available + IR-projection coordination needed

## Why this archives without implementation

This change describes parsing modm-devices' `<driver name="timer">`
blocks for STM32 timer / PWM tier-2/3/4 metadata.  Two independent
blockers stand between this proposal and a clean implementation:

1. **modm-devices XML is not cached locally.**  The earlier
   modm-devices port (Phase 1.7 of the autonomous round) used a
   worktree-resident copy that has since been cleaned up; nothing
   under `alloy-codegen/.cache/sources/modm-devices` carries the
   XML files this change parses.  Adding the source pin would
   work, but the maintainer should review the modm SHA before
   making the modm pin "load-bearing" for STM32 emission.

2. **The `device.timer_*` / `device.pwm_*` IR fields don't have a
   projection in the canonical YAML schema.**  A grep of
   `schema/canonical_device/device.schema.json` shows no
   `timer_prescaler_options`, `timer_trigger_sources`,
   `pwm_alignment_options`, `pwm_break_inputs`, or
   `timer_mode_flags` keys.  The proposal's "every field consumed
   already exists on `CanonicalDeviceIR`" refers to alloy-codegen's
   in-memory IR class, not the canonical YAML schema — meaning
   either:
   - the YAML schema needs an additive minor bump to add a
     `tier_data` block, *or*
   - alloy-codegen needs an IR-projection layer that derives
     these fields from a generic `capabilities` payload entry.
   That coordination wasn't possible in a single-session pass.

## What's needed before this can land

- A pinned modm-devices SHA in `data/source_pins.toml` plus a
  fetched `<modm-root>/devices/stm32/<series>/<chip>.xml` cache.
- Either a schema bump that introduces canonical tier fields, or
  agreement to project tier data through the existing
  `capabilities` entry with a documented sub-shape.
- A test fixture under `tests/fixtures/modm/<device>/` shipping a
  representative modm chip XML so the parser can be exercised
  offline.

## What survives in tree

- The OpenSpec proposal + tasks remain in this archive directory
  as a record of intended scope.
- The existing `alloy_data_extractor.extractors.modm_devices`
  parser already covers RCC clock-tree edges + DMA request
  matrix + AF tables; adding the timer / PWM tier helpers would
  follow the same pattern.

## Where to look next

* `extractors/modm_devices.py` — current parser surface.
* `data/source_pins.toml::modm-devices` — pin entry awaiting a
  cached SHA.
* alloy-codegen's `consume-alloy-devices-yml-as-canonical-input`
  archive for the IR-vs-YAML coordination story.
