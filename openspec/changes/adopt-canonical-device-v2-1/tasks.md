# Tasks — adopt-canonical-device-v2-1

## Phase 1 — Schema in tree

- [ ] 1.1 Move `proposals/canonical-v2-handcrafted/schema/`
      to `schema/canonical_device_v2_1/` in alloy-codegen.  Mirror
      the same directory in alloy-devices-yml so both repos can
      validate independently (single source of truth: bump in lockstep
      via a tiny CI workflow that fails when the two diverge).
- [ ] 1.2 alloy-codegen: add a packaging entry so the schema JSON +
      validator ship inside the wheel (`importlib.resources` path).
- [ ] 1.3 alloy-data-extractor: vendor a tested copy of the
      validator at `src/alloy_data_extractor/schema/validate.py`
      pointing at the bundled JSON.  Same module the writer imports
      in Phase 3.

## Phase 2 — IR + reader/writer (alloy-codegen)

- [ ] 2.1 New module `alloy_codegen.ir.v2_1.identity` — `Identity`,
      `Core`, `Multicore`, `MulticoreCore` dataclasses; `core.bits` is
      a `Literal[8, 16, 32, 64]`.
- [ ] 2.2 `alloy_codegen.ir.v2_1.memory` — `MemoryRegion` with
      `address_space: Literal["program","data","instruction","eeprom","fuse","signature"] | None`,
      `backing: str | None`, `role: str | None`.
- [ ] 2.3 `alloy_codegen.ir.v2_1.clock` — `Oscillator`, `PLLConfig`,
      `ClockDomain`, `ClockProfile`, `SelectRegister`, `SelectTask`.
- [ ] 2.4 `alloy_codegen.ir.v2_1.templates` — `Template`,
      `TemplateRegister`, `TemplateField` (with `enum: dict[str,int] | None`),
      `TimerExtras` (slave-mode trigger, master-output, deadtime),
      `BreakInputs`.  `Template.fields` is the opt-in subset.
- [ ] 2.5 `alloy_codegen.ir.v2_1.peripherals` — `PeripheralInstance`
      (with `template`, `ip_version`, `mutex_group`,
      `max_clock_override`, `pin_options`, `dma`, `irq`, `rcc`,
      `calibration`, `external_triggers`, `timing_presets`,
      `trigger_source_peers`, `channels`, `capabilities_extra`,
      `conflicts_with`).
- [ ] 2.6 `alloy_codegen.ir.v2_1.pinout` — `Pin`, `PinConstraint`
      `Literal` enum exactly matching the 18 schema tags.
- [ ] 2.7 `alloy_codegen.ir.v2_1.interrupts` — `VectorTable` (list)
      and `InterruptMatrix` (object with `internal_per_cpu` +
      `peripheral_sources`).
- [ ] 2.8 `alloy_codegen.ir.v2_1.device.CanonicalDevice` — top-level
      aggregate; `slots=True, frozen=True` like the rest.
- [ ] 2.9 New `alloy_codegen.canonical_device_v2_1` module:
      * `parse_device(text)` — YAML → `CanonicalDevice`.
      * `serialize_device(ir)` — `CanonicalDevice` → YAML.  Emits
        deterministic key order matching the v2.1 cheat-sheet.
      * `validate_device(text)` — schema-validate without parsing.
      * `parse_device_payload(payload)` — skip the YAML round-trip
        when the caller already has a primitive.
      * Schema-load is `@functools.cache`d.
- [ ] 2.10 Replace `bootstrap.IR_SCHEMA_VERSION = "1.5.0"` with
      `bootstrap.CANONICAL_SCHEMA = "alloy.device.v2.1"`.  Audit every
      caller (16 references across runtime_lite_emission, manifests,
      validation, normalize stage) to switch the constant name +
      semantics.
- [ ] 2.11 Pytest `tests/test_canonical_device_v2_1.py`:
      * round-trip every admitted YAML byte-for-byte
      * negative tests (link the 7 `negative-tests/*.yml` files)
      * `parse_device(serialize_device(parse_device(text)))` is byte-
        equal to the input
      * `CANONICAL_SCHEMA` constant is exactly `"alloy.device.v2.1"`

## Phase 3 — Synthesised rows (alloy-codegen)

The "alloy-codegen synthesises these from raw fields" sections move
out of the on-disk YAML into in-memory IR populated by
`connector_model.build_synthesised(ir: CanonicalDevice)`.

- [ ] 3.1 `alloy_codegen.ir.synthesised.route_operations` — typed
      `RouteOperation` with `target_ref`, `value_ref`, `register_id`,
      `register_field_id`.  Built from `peripherals[].rcc.en/rst` +
      template register/field map.
- [ ] 3.2 `alloy_codegen.ir.synthesised.route_requirements` — pinmux
      bonded-pin / package / selector requirements, built from
      `peripherals[].pin_options` + `pinout`.
- [ ] 3.3 `alloy_codegen.ir.synthesised.connection_candidates` +
      `connection_groups` — per-package valid pin↔signal routes.
- [ ] 3.4 `alloy_codegen.ir.synthesised.interrupt_bindings` +
      `vector_slots` — typed peripheral→IRQ bindings;
      `vector_slots.kind` populated from peripheral templates.
- [ ] 3.5 `alloy_codegen.ir.synthesised.startup_descriptors` —
      typed startup events derived from `clock.profiles[]` +
      `memory[].alias`.
- [ ] 3.6 `connector_model.build_synthesised` returns a
      `SynthesisedDevice` aggregate that emitters consume alongside
      the on-disk `CanonicalDevice`.
- [ ] 3.7 Pytest `tests/test_synthesised_rows.py`: every admitted chip
      synthesises a non-empty set of route_operations and the IRQ
      bindings reach the typed contract `validation.py` enforces.

## Phase 4 — Emitter rewrites (alloy-codegen)

- [ ] 4.1 `runtime_lite_emission.py` — register / field access goes
      via `device.templates[<ip>].registers[<name>].offset` and
      `device.templates[<ip>].fields[<reg>.<name>]`.  No flat
      `register_fields[]` lookup remains.
- [ ] 4.2 `emission.py` (every codegen path) — same.
- [ ] 4.3 `validation.py` — gate `c1`/`c2`/`c3` content checks
      rewired to read v2.1 IR.  Drop the `is None` checks on the
      diagnostic echo fields (they no longer exist).
- [ ] 4.4 `runtime_reports.py` — the audit/explainability output
      reads `provenance` from the top-level (no per-row blocks); for
      synthesised rows it reads each row's typed origin tag instead.
- [ ] 4.5 `runtime_clock_init.py`, `runtime_resets.py`,
      `runtime_interrupt_stubs.py` — rewrite to consume v2.1 +
      synthesised IR.  Profiles drive the clock-init recipe.

## Phase 5 — Extractor rewrite (alloy-data-extractor)

- [ ] 5.1 New `alloy_data_extractor.emit.canonical_yaml_v2_1` writer.
      `write_device_yaml(payload, *, output_root, vendor, family, device)`
      schema-validates pre-emit; `yaml.dump` with deterministic top-
      level order matching the v2.1 cheat-sheet.  The OLD
      `emit/canonical_yaml.py` is **deleted** in the same commit.
- [ ] 5.2 Per-vendor extractor rewrites (each is its own subtask).
      The merge engine's `STM32_MERGE_POLICY` and field-priority paths
      shift to v2.1 namespaces.

  - [ ] 5.2.1 `cmsis_svd.py` — emits `templates.<ip>` (one per
        peripheral_class × ip_version), `peripherals[].template`,
        `interrupts[]`.  Per-row provenance gone (top-level only).
  - [ ] 5.2.2 `stm32.py` — primary; populates v2.1 identity, memory,
        peripherals, interrupts.
  - [ ] 5.2.3 `stm32_cubemx.py` — fills `peripherals[].ip_version`,
        `pinout[].constraints` (5V-tolerance), `clock.profiles[]`
        candidates from CubeMX clock-tree XML, `cubemx_peripherals`
        enrichment vanishes (folded into `peripherals[].ip_version`).
  - [ ] 5.2.4 `stm32_tier.py` — `templates.<ip>.options` + `options.*_encoding`
        instead of the flat tier-2/3/4 lists.
  - [ ] 5.2.5 `stm32_overlay.py` — `peripherals[adc1].calibration`,
        `peripherals[i2c1].timing_presets`, `clock.profiles[]`,
        `pinout[].constraints` (5V-tolerance), `peripherals[].max_clock_override`.
  - [ ] 5.2.6 `microchip_atdf.py` — emits AVR + SAM templates; AVR's
        Harvard `address_space` populated.
  - [ ] 5.2.7 `nordic_zephyr_dts.py` — `pin_options.{psel: true}`
        flag, `mutex_group` for SPIM/TWIM/UARTE shared bases.
  - [ ] 5.2.8 `espressif_svd.py`, `espressif_clock_tree.py`,
        `espressif_soc_caps.py` — `pin_options.{matrix: true}`,
        DPORT clock-enable bits via `peripherals[].rcc.en`,
        per-CPU vector base under `core.multicore`.
  - [ ] 5.2.9 `nxp_imxrt.py` — XIP + tightly-coupled-memory regions.
  - [ ] 5.2.10 `raspberrypi_pico_sdk.py` — PIO template,
        `function: <0..8>` pin_options, dual-core symmetric,
        external QSPI flash.
  - [ ] 5.2.11 `modm_devices.py` — fills clock-tree gaps via
        secondary enrichment.
  - [ ] 5.2.12 `pic.py`, `msp430.py`, `8051.py` — small extractor
        ports.

- [ ] 5.3 `merge.py` rewires field priorities to v2.1 paths
      (`templates.usart.options`, `peripherals[].pin_options`,
      `peripherals[adc1].calibration`, …).  Drop helpers that handled
      v1-specific tier flat lists.
- [ ] 5.4 `extractor_protocol.py` — `ExtractionResult.payload` typed
      as `V21Payload` (a `TypedDict` matching the schema).  Old
      free-form `dict[str, Any]` is gone.

## Phase 6 — Soak (parallel run)

- [ ] 6.1 New CLI `scripts/dual_emit_compare.py` runs both pipelines
      against every admitted device and writes:
      * `out/v1/<chip>.yml` — current (legacy) output
      * `out/v2_1/<chip>.yml` — new output
      * `out/diff/<chip>.txt` — semantic diff (peripherals,
        templates, pinout) ignoring shape changes
- [ ] 6.2 Reviewer pass — open `diff/*` for every admitted chip;
      file follow-up issues for any genuine fact loss.  Empty diff =
      green for that chip.
- [ ] 6.3 CI workflow `soak-canonical-v2-1` runs once per night during
      the soak window; opens an issue if a chip's diff turns red.
- [ ] 6.4 Minimum two consecutive nights green before cutover.

## Phase 7 — Cutover (one PR per repo, merged in lockstep)

- [ ] 7.1 alloy-devices-yml: replace every `vendors/**/devices/*.yml`
      with the v2.1 output from Phase 6.  Same commit drops the old
      `schema/canonical_device/` directory.  Bump
      `coverage-dashboard.md` regenerator.
- [ ] 7.2 alloy-codegen: delete `alloy_codegen.ir.model`,
      `alloy_codegen.canonical_device_yaml`,
      `bootstrap.IR_SCHEMA_VERSION`, the legacy `parse_device_payload`
      / `_expand_provenance_defaults` helpers.  Move the new
      `canonical_device_v2_1` module to `canonical_device.py` (the
      new public name).
- [ ] 7.3 alloy-codegen: bump submodule pin in `data/devices` to the
      new alloy-devices-yml SHA.
- [ ] 7.4 alloy-data-extractor: delete the old `emit/canonical_yaml.py`
      module + `scripts/compact_canonical_yamls.py` (no longer
      needed; v2.1 has nothing to compact).  The
      `STM32_MERGE_POLICY` priorities migrate to v2.1 paths.
- [ ] 7.5 Three commits land within the same hour, in this order:
      data-yml → codegen → data-extractor (extractor depends on
      codegen's `CanonicalDevice` typed import).

## Phase 8 — Tests + goldens + docs

- [ ] 8.1 alloy-codegen: regenerate every emitted-artifact golden
      via `ALLOY_UPDATE_GOLDENS=1 pytest tests/test_emit.py`.
      Inspect manually for content drift; size shrink is expected.
- [ ] 8.2 alloy-codegen: full pytest run green
      (`python3 -m pytest tests/ --timeout=120 -q`).
- [ ] 8.3 alloy-data-extractor: full pytest run green; per-vendor
      goldens regenerated (each vendor pytest under
      `tests/test_<vendor>.py`).
- [ ] 8.4 alloy-devices-yml: CI workflow `validate-v21` green; the
      `index.yml` regenerator targets v2.1.
- [ ] 8.5 README updates in all three repos pointing at the v2.1
      schema doc + cheat-sheet.
- [ ] 8.6 Migration note in each repo's `CHANGELOG`.
- [ ] 8.7 Archive `compact-canonical-yaml-and-cache-loads` Phase 2
      (`provenance_defaults` writer) — the helper is now dead code,
      but the OpenSpec stays in `archive/` for traceability.

## Phase 9 — Validate + archive

- [ ] 9.1 `openspec validate adopt-canonical-device-v2-1 --strict` →
      green.
- [ ] 9.2 `openspec archive adopt-canonical-device-v2-1` after
      Phase 7 + 8 land in main on all three repos.
- [ ] 9.3 Cross-repo final commit message includes the SHAs of the
      three coordinated PRs so reviewers can trace the cutover.
