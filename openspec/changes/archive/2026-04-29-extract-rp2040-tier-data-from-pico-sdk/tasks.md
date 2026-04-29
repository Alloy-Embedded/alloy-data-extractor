# Tasks — extract-rp2040-tier-data-from-pico-sdk

## Phase 1: I2C tier parser

- [ ] 1.1 Add `parse_i2c_tier(pico_sdk_root) -> I2cTierData`
      helper to `alloy_data_extractor.extractors.rp2040`.
      Parse `src/rp2_common/hardware_i2c/i2c.c` for the
      speed-mode whitelist used by `i2c_init()`.
- [ ] 1.2 Synthesise three `i2c_speed_options` rows:
      `(100_000, "standard")`, `(400_000, "fast")`,
      `(1_000_000, "fast_plus")`.
- [ ] 1.3 Compute `i2c_timing_presets` for each canonical
      source-clock frequency (12 / 48 / 80 MHz) using the
      formula in `i2c.c::i2c_set_baudrate()`.

## Phase 2: PWM tier parser

- [ ] 2.1 Add `parse_pwm_tier(pico_sdk_root) -> PwmTierData`
      helper.  Parse
      `src/rp2_common/hardware_pwm/include/hardware/pwm.h`
      for `PWM_DIV_INT_MIN/MAX` and the
      `pwm_chan_level_t` enum.
- [ ] 2.2 Project the alignment options onto
      `device.pwm_alignment_options` — RP2040 has 2 modes
      (edge, center-aligned).
- [ ] 2.3 RP2040 has no dead-time or break-input register —
      keep `device.pwm_deadtime_options` and
      `device.pwm_break_inputs` empty (the trait emit handles
      both as `std::array<uint8_t, 0>{}`).
- [ ] 2.4 Set `pwm_mode_flags`:
      - `supports_combined_pwm = True` (the PWM_CSR.PH_CORRECT
        bit lets channels A/B share a slice)
      - `supports_asymmetric_pwm = True`
      - `supports_complementary_outputs = False`
      - `supports_deadtime = False`
      - `supports_break_input = False`

## Phase 3: Timer tier parser

- [ ] 3.1 Add `parse_timer_tier(pico_sdk_root) -> TimerTierData`
      helper.  RP2040 timer is the central 64-bit counter +
      4 alarm comparators (no master-output mode like ARM
      advanced timers).
- [ ] 3.2 Project `timer_master_outputs` as 4 entries (one
      per alarm), each with `(name="ALARM<N>", field_value=N)`.
- [ ] 3.3 Project `timer_trigger_sources` as the per-alarm
      DREQ list — re-use the existing
      `Rp2040TimerControllerHwDescriptor.alarm_dreqs` field
      that already carries the data.
- [ ] 3.4 `timer_prescaler_options`: empty — RP2040 timer
      runs from a fixed 1 µs tick (clk_ref / `clk_ref_freq`).
- [ ] 3.5 Set `timer_mode_flags`:
      - `supports_dma_burst = True` (alarm DREQs)
      - `supports_repetition_counter = False`
      - `supports_xor_input = False`

## Phase 4: IR projection + re-extraction

- [ ] 4.1 Wire all three helpers into the rp2040 extractor's
      IR-building step.
- [ ] 4.2 Re-extract YAMLs for `pico` and `rp2040`.
- [ ] 4.3 Verify each YAML carries:
      - `i2c_speed_options >= 3`
      - `pwm_alignment_options >= 2`
      - `timer_master_outputs >= 4`
- [ ] 4.4 Round-trip via
      `alloy_codegen.sources.alloy_devices_yml.load_canonical_device`.

## Phase 5: Tests

- [ ] 5.1 Per-helper unit test in alloy-data-extractor:
      `test_rp2040_tier_data.py` parametrised over (pico,
      rp2040).  Each asserts the expected counts + the
      mode-flag values for I2C / PWM / Timer.
- [ ] 5.2 Snapshot fixture under
      `tests/fixtures/rp2040/<device>/` with the parsed
      `I2cTierData` / `PwmTierData` / `TimerTierData` so
      future pico-sdk bumps trip a deliberate review.

## Phase 6: Spec + final checks

- [ ] 6.1 Spec delta in
      `specs/vendor-coverage/spec.md` — rp2040 extractor
      SHALL project I2C / PWM / Timer tier data from the
      pico-sdk.
- [ ] 6.2 `openspec validate
      extract-rp2040-tier-data-from-pico-sdk --strict` passes.
- [ ] 6.3 `pytest -q` + `ruff check` clean.
- [ ] 6.4 Push regenerated YAMLs to alloy-devices-yml.
