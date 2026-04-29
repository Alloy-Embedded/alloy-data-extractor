# Tasks — extract-tier-2-3-4-data-from-modm

## Phase 1: Timer tier parser

- [ ] 1.1 Add `parse_timer_tier_data(timer_block,
      peripheral_name)` helper to
      `alloy_data_extractor.extractors.modm_devices`.  Returns a
      `TimerTierData` dataclass with `prescaler_options`,
      `trigger_sources`, `master_outputs`, `mode_flags`.
- [ ] 1.2 Walk every modm `<driver name="timer">` element under
      a device and accumulate one `TimerTierData` per timer
      instance.
- [ ] 1.3 Map modm's trigger nicknames (ITR0 / ITR1 / TI1F_ED /
      TI1FP1 / TI2FP2 / ETRF) to the canonical
      `(name, field_value)` tuples expected by
      `device.timer_trigger_sources`.

## Phase 2: PWM tier parser

- [ ] 2.1 Add `parse_pwm_tier_data(timer_block,
      peripheral_name)` — the modm `pwm` capability lives on
      the same `<driver name="timer">` block via the
      `<advanced/>` and `<break_input/>` sub-elements.
- [ ] 2.2 Project alignment modes (edge / center-aligned-1 /
      center-aligned-2 / center-aligned-3) into
      `device.pwm_alignment_options`.
- [ ] 2.3 Project `<break_input>` rows into
      `device.pwm_break_inputs`.

## Phase 3: IR projection

- [ ] 3.1 Update the modm extractor's IR-building step (or
      `normalize.modm` if that's where IR projection lives) to
      pass the parsed tier data into the canonical IR's six
      timer / PWM fields.
- [ ] 3.2 Re-extract YAML for the 6 admitted STM32 devices.
- [ ] 3.3 Verify each YAML carries the expected non-empty tier
      tuples (use the IR loader directly via
      `alloy_codegen.sources.alloy_devices_yml.load_canonical_device`).

## Phase 4: Tests

- [ ] 4.1 Per-device unit test in alloy-data-extractor:
      `test_modm_timer_tier_data.py` parametrised over 6 STM32
      devices.  Each asserts the expected counts:
      `device.timer_trigger_sources >= 4`,
      `device.timer_master_outputs >= 6`,
      `device.timer_mode_flags == True for repetition_counter`.
- [ ] 4.2 Snapshot fixture under `tests/fixtures/modm/<device>/`
      with the parsed `TimerTierData` so future modm bumps trip
      a deliberate review.

## Phase 5: Spec + final checks

- [ ] 5.1 Spec delta in
      `specs/vendor-coverage/spec.md` — modm extractor SHALL
      project Timer + PWM tier data when present.
- [ ] 5.2 `openspec validate
      extract-tier-2-3-4-data-from-modm --strict` passes.
- [ ] 5.3 `pytest -q` + `ruff check` clean.
- [ ] 5.4 Push the regenerated YAMLs to alloy-devices-yml and
      open a PR linking back to this change.
