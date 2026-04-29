# Tasks — complete-stm32-tier-coverage

## Phase 1: SVD `<enumeratedValues>` projection (universal)

- [x] 1.1 Extended `cmsis_svd._register_and_field_records` to
      walk every `<field><enumeratedValues><enumeratedValue>`
      block.  Added `_parse_field_enumerations()` helper.  Flat
      `register_field_enumerations` list emitted with
      `(field_id, peripheral, register_name, field_name, name,
      raw_value, description, usage, provenance)` rows, sorted
      by `(field_id, usage, raw_value)`.
- [x] 1.2 Handled `<enumeratedValues derivedFrom="...">`
      inheritance via a two-pass resolver
      (`_resolve_derived_enumerations()`).  Three resolution
      modes: full path `PERI.REG.FIELD`, peripheral-relative
      `REG.FIELD`, and bare `FIELD` (name-only fallback).
      Missing references drop silently.
- [x] 1.3 Honored `<usage>` element on `<enumeratedValues>`.
      Default `read-write`; `read` and `write` blocks emit two
      separate row groups carrying their respective usage tag.
- [x] 1.4 Wired `register_field_enumerations` into the
      `extract_device()` payload and added it to
      `_TOP_LEVEL_KEY_ORDER` after `register_fields`.
- [x] 1.5 Bumped `SCHEMA_VERSION_CURRENT` 1.3.0 → 1.4.0
      (additive, optional) + bumped `MERGED_SCHEMA_VERSION` to
      match.  The bundled JSON schema in `alloy-devices-yml` is
      permissive (`additionalProperties: true`) so it
      auto-accepts the new field; no schema-file edit required.
- [x] 1.6 Tests under `test_cmsis_svd_extractor.py` (8 new):
      concrete enum extraction, read+write usage split, three
      derivedFrom forms, derivedFrom-via-peripheral propagation,
      per-row provenance, key-presence in the canonical
      payload, deterministic sort.  Verified against the cached
      `STM32G071.svd`: 559 enum rows.
- [x] 1.7 Verified mimxrt1062 extraction still produces valid
      payload — added bonus 29,739 enum rows from the NXP
      SoC SVD (which annotates enums very thoroughly).
      Full pytest suite: 251 passed / 2 skipped (was 243).
      Merged stm32g071rb re-emit grows from 59,620 → 66,330
      lines (90% of canonical's 73,410).

## Phase 2: stm32-tier secondary extractor

- [x] 2.1 Created `extractors/stm32_tier.py` registered as
      secondary `("__stm32_tier_secondary__","…")`.  Walks the
      CubeMX MCU XML directly (independent re-read) to discover
      peripheral instances + IP versions.
- [x] 2.2 `extractors/stm32_tier_mappings.py` ships
      9 TierMapping entries: USART_SCI3_V2, USART_SCI2_V1,
      SPI_V3, I2C_V1, ADC_G0_V3, ADC_F4_V3, TIMER_GPTIMER_V3,
      TIMER_F4_ADV, TIMER_F4_GP.  Initial coverage targets
      STM32G0 (full) + STM32F4 (USART/ADC/timer subset).
- [x] 2.3 Hardcoded projection rows live inline in the mapping
      tables (USART data_bits/parity/stop_bits/mode_flags,
      SPI baud_prescaler, ADC resolution/sample_time/
      oversampling/external_triggers, timer master_outputs/
      trigger_sources/prescaler, PWM alignment/break_inputs/
      deadtime/mode_flags).  The original "project from SVD
      enums" plan was downgraded after observing wildly uneven
      enum coverage in cmsis-svd-data community SVDs — STM32G071
      ships enums for ADC + TIM15 only, STM32F405 ships zero.
      Hardcoded per-IP-version constants deliver tier-3
      deterministically regardless of SVD richness, with
      identical maintenance cost (one edit per IP version).
- [x] 2.4 Computed projections embedded in mapping rows:
      `timer_prescaler_options` rendered sparse (1, 2, 4 …
      65536 — 17 powers-of-2 entries) since the full 65,536-row
      table would bloat the YAML; `pwm_deadtime_options`
      emitted as 4 range rows matching the BDTR.DTG non-linear
      encoding.
- [x] 2.5 Mode-flag rows hardcoded per IP version (advanced
      timers get `supports_repetition_counter=True` etc.;
      general-purpose timers get the non-advanced subset).
      Field-presence detection from the SVD register tree was
      the original plan — collapsed into per-IP-version
      constants for the same reason as 2.3 (more deterministic,
      one edit per IP version).
- [x] 2.6 IP versions resolved by re-parsing the CubeMX MCU XML
      via the existing `stm32_cubemx._parse_mcu_xml` helper —
      the per-instance `<IP Version="…">` attribute is now also
      surfaced in stm32-cubemx's payload as
      `cubemx_peripherals[]` for downstream auditing.
      `STM32_MERGE_POLICY` extended with 18 tier-field-priority
      rules routing each tier array through `stm32-tier`.
- [x] 2.7 Tests under `test_stm32_tier_extractor.py` (19 new):
      version-pattern dispatch (parametric over 6 IPs);
      cross-instance dedup; cross-IP-version row union;
      unmapped-instance skip; deterministic sort; provenance
      stamping; resolver-secondary; missing-source raises;
      warning surface for unmapped IPs; synthetic-DB end-to-end
      (15 tier fields populated); real-DB smoke test against
      the locally installed CubeMX.  Verified the merged
      stm32g071rb pipeline lights up 18 tier-3/4 fields via
      this projector alone.

## Phases 3 + 4: Absorbed into Phase 5

The original Phase 3 plan to extract `adc_internal_channels`
from CubeMX MCU XML pin annotations turned out to rest on a
false premise — inspection of the real CubeMX XMLs (G071,
F407) showed the internal channels are **not** declared as
``<Pin>`` entries.  CubeMX exposes them only as
``<PossibleValue>`` rows in the per-IP ADC XML
(`ADC-aditf4_v3_0_Cube_Modes.xml`), without numeric channel
indices — those live in CMSIS device headers
(`stm32g071xx.h`).

Phase 4 (CMSIS-headers parser) was then blocked on staging the
`STMicroelectronics/cmsis_device_<family>` repos; the local
copies on this workstation were OneDrive placeholder files
(zero bytes after `xxd`).

Both phases were absorbed into the Phase 5 family-overlay
TOML — calibration ROM addresses, internal channel maps, and
calibration-context constants are family-uniform and fit the
overlay shape cleanly.  A future Phase 4 follow-up can wire a
real `stm32-cmsis-headers` extractor that **regenerates** the
overlay TOML rows from staged headers as a verification + drift
gate.

- [x] 3-absorbed `adc_internal_channels` populated via the
      family overlay (`adc.internal_channels`) — STM32G0:
      vrefint=ch13, temperature_sensor=ch12, vbat=ch14;
      STM32F4: ch17 / ch16 / ch18.
- [x] 4-absorbed `adc_calibration_context` +
      `adc_calibration_data_points` populated via the family
      overlay (`adc.calibration_context` +
      `adc.calibration_data_points`).  Addresses sourced from
      ST CMSIS LL macros (cited in the TOML comments).

## Phase 5: Family-overlay TOMLs

- [x] 5.1 Created `extractors/stm32_overlay.py` — secondary
      EnrichmentExtractor that reads
      `data/vendors/st/<family>/family.toml` and per-device
      overrides at `data/vendors/st/<family>/devices/<device>.toml`.
      Deep-merges with per-device-wins semantics; per-row
      provenance stamps `source_id="stm32-overlay"` plus the
      TOML's relative path.  Out-of-tree overlay roots
      (test fixtures) fall back to the basename for path stability.
- [x] 5.2 TOML schema covers ADC (`max_clock_hz`,
      `calibration_context`, `calibration_data_points`,
      `internal_channels`), UART (`max_baud_hz`), I2C
      (`speed_options`, `max_clock_hz`), system_clock
      (`post_reset_profile`, `recommended_profiles`).
- [x] 5.3 Bootstrap family overlays — STM32G0 + STM32F4
      shipped, sourced from RM0444 / RM0090.  STM32G4 / L4 /
      H7 / U5 are deferred to follow-up sessions (same shape;
      no new code needed).
- [x] 5.4 `STM32_MERGE_POLICY` extended with 9 new field-priority
      rules routing the overlay-derived fields through
      `stm32-overlay` (`adc_calibration_*`, `adc_internal_channels`,
      `adc_max_clock_hz`, `uart_max_baud_hz`, `i2c_speed_options`,
      `i2c_max_clock_hz`, `i2c_timing_presets`,
      `system_clock_profiles`).
- [x] 5.5 Tests under `test_stm32_overlay_extractor.py` (10):
      family-only TOML, per-device override deep-merge, missing
      overlay returns empty, projection round-trip, real
      stm32g0 family TOML end-to-end, secondary-resolver
      invariant, missing-overlay warning surface.

## Phase 6: I2C timing-preset computation

- [x] 6.1 `extractors/stm32_i2c_timing.py` implements the ST
      AN4235 §3.1.2 formula: PRESC selected for
      ~125 ns / 62.5 ns t_PRESC (standard / fast-plus); SCLL
      and SCLH split 50/50 (standard) or 60/40 (fast / fast-
      plus); SCLDEL ≥ tSU;DAT_min / t_PRESC; SDADEL clamped to
      tHD;DAT_min budget.  `I2cTimingPreset` dataclass exposes
      a `timingr_value` property packing PRESC/SCLDEL/SDADEL/
      SCLH/SCLL into the canonical TIMINGR layout.
- [x] 6.2 Wired into `stm32_overlay`: when both
      `i2c.speed_options` and `system_clock_profiles` are
      present, the cross-product is computed and emitted as
      `i2c_timing_presets[]` with per-row provenance.  Real
      stm32g0 overlay → 6 presets (3 speeds × 2 sysclks).
- [x] 6.3 Tests under `test_stm32_overlay_extractor.py` (7):
      basic shape, parametric over (100k / 400k / 1M),
      determinism, unsupported-speed raises, zero-clock
      rejects, cross-product order + count, end-to-end via
      overlay extractor.

## Phase 7: Bulk re-emit + verification

- [ ] 7.1 Driver script
      `scripts/reemit_stm32_with_full_tier.py` composing the
      pipeline: SVD primary ⊕ cubemx ⊕ cmsis-headers ⊕
      stm32-tier ⊕ stm32-overlay → merge → write_device_yaml.
- [ ] 7.2 Re-emit YAML for each of the 5 admitted ST devices
      to a sandbox output root.  Compare against the existing
      canonical YAML in alloy-devices-yml.
- [ ] 7.3 Tier-coverage assertion: every re-emitted YAML
      carries ≥ 23 tier-2/3/4 fields populated (parity with
      the existing g071rb).  Drift report per-field for any
      mismatch vs the existing canonical.
- [ ] 7.4 Schema validation: every re-emitted YAML passes
      `validate_yaml_file` against the bundled schema.
- [ ] 7.5 Land the re-emitted YAMLs into alloy-devices-yml on
      a feature branch for review (do not push to main).
- [ ] 7.6 Document the new pipeline in
      `docs/stm32-tier-pipeline.md` (or the README) — single
      diagram + table of which extractor owns which field.

## Phase 8: Spec + final checks

- [ ] 8.1 `openspec validate complete-stm32-tier-coverage --strict`
      passes.
- [ ] 8.2 `pytest -q` clean (target ≥ 280 passed).
- [ ] 8.3 Archive — kept open until Phase 7.5 lands the
      regenerated YAMLs in alloy-devices-yml.
