# Adopt canonical device v2.1 — drop v1, no legacy bridge

## Why

Five hand-written reference YAMLs and the audit at
`proposals/canonical-v2-handcrafted/` showed that the canonical-v1
shape carries 3 KB – 6 MB per chip, leaks ~30 % of bytes to per-row
provenance, and forces every register-heavy IP to be re-emitted per
peripheral instance.  v2.1 settled on a different shape:

* `templates:` block — one per IP version — collapses repeated register
  layouts (40-150× smaller register data on chips with multiple USART /
  SPI / TIMER instances).
* `peripherals[].template + ip_version` reference the template; per-
  instance scope only carries `base / bus / irq / rcc / dma / pin_options`.
* Hand-crafted v2.1 YAMLs total **3 019 lines / 128 KB** for five very
  different MCUs (STM32F1, AVR, ESP32, nRF52, RP2040).  The auto-
  extracted v1 of the same chips totals ~13 MB raw / ~7 MB compacted.
* All 13 audit deltas (pin constraints, ADC calibration ROM, I²C
  TIMINGR presets, named clock profiles, `select_register`,
  `timer_advanced`, …) are first-class in v2.1.
* JSON-schema + Python validator at
  `proposals/canonical-v2-handcrafted/schema/` already gates 5 positive
  + 7 negative cases.

Carrying both v1 and v2.1 through the pipeline is dead weight — the
extractors, the codegen IR, the merge engine, the `provenance_defaults`
expander, the cache, the bulk-admit script, and the tests would all
need a fork per shape.  We adopt v2.1 as the **single** canonical form
and delete every v1 emission / consumption path.

## What Changes

This change set spans all three repos.  No backward-compatibility
shim is provided — chips that haven't been re-emitted into v2.1 simply
fall out of the registry until they are.

### alloy-codegen

* New IR dataclass tree under `alloy_codegen.ir.v2_1.*` modelling the
  v2.1 shape directly (templates, profiles, calibration, pin
  constraints, …).  The legacy `alloy_codegen.ir.model` is removed
  entirely; consumers are rewritten against the new tree.
* New reader/writer at `alloy_codegen.canonical_device_v2_1` —
  `parse_device(text)` returns the new IR; `serialize_device(ir)`
  emits a v2.1 YAML.  Old `canonical_device_yaml` is deleted.
* Schema files relocated to `schema/canonical_device_v2_1/` (the
  `proposals/` copy is the source of truth; codegen vendors a copy at
  install time).
* `bootstrap.IR_SCHEMA_VERSION` retired; replaced with
  `CANONICAL_SCHEMA = "alloy.device.v2.1"`.  The semver compatibility
  check is gone — version is checked exactly.
* `connector_model.py` rewrites: synthesises `route_operations`,
  `route_requirements`, `connection_candidates`, `vector_slots`,
  `interrupt_bindings` from the new template + peripheral instances.
  These rows still live only in the in-memory IR, never serialised.
* `runtime_lite_emission.py`, `emission.py`, `validation.py` and every
  emitter rewires register / field access through `templates.<ip>`
  rather than the flat `register_fields[]` / `registers[]` lists.
* Binary IR cache key bumps from `IR_SCHEMA_VERSION` to
  `CANONICAL_SCHEMA`.  All existing pickles invalidate.

### alloy-data-extractor

* New writer `alloy_data_extractor.emit.canonical_yaml_v2_1` — writes
  a v2.1 YAML from the in-memory primitive payload.  Old
  `emit/canonical_yaml.py` is deleted; the `_compact_provenance_defaults`
  helper is no longer needed (v2.1 has no per-row provenance).
* Per-vendor pipelines (`stm32`, `cmsis_svd`, `stm32_cubemx`,
  `stm32_tier`, `stm32_overlay`, `microchip_atdf`, `nordic_zephyr_dts`,
  `espressif_*`, `nxp_imxrt`, `raspberrypi_pico_sdk`, `modm_devices`,
  `pic`, `msp430`, `8051`) rewrite their `extract()` outputs to fill
  the v2.1 primitive shape directly.  No intermediate v1 emission +
  conversion step.
* `merge.STM32_MERGE_POLICY` and the field-priority engine carry over
  but operate on v2.1 paths (`templates.<ip>.fields`, `peripherals[]`,
  `clock.profiles[]`, `pinout[].constraints`, …) instead of the
  flattened v1 sections.
* `scripts/reemit_stm32_with_full_tier.py`, `scripts/compact_canonical_yamls.py`,
  and the bulk-admit pipeline rewrite to the v2.1 surface.
* A new `scripts/audit_v1_to_v2_1.py` walks every YAML under
  alloy-devices-yml and reports which chips need re-emission (initial
  state: all of them).

### alloy-devices-yml

* Repository content fully replaced.  Every admitted YAML is re-emitted
  through the v2.1 pipeline; the file format declared at the top of
  each file changes from `schema_version: 1.5.0` to `schema:
  alloy.device.v2.1`.
* Schema submodule replaced — `schema/canonical_device/*` retired in
  favour of `schema/canonical_device_v2_1/*`.
* CI workflows updated to validate every PR via the new validator
  (`schema/canonical_device_v2_1/validate.py`).
* `tools/` helpers (index builder, coverage dashboard generator) read
  the v2.1 shape.

## Impact

* **Breaking** for every consumer of the canonical YAMLs (alloy-codegen,
  alloy-cli, alloy-runtime, anyone reading the data repo directly).
* Reduces the alloy-devices-yml repository from ~30 MB (v1 compacted)
  to an estimated **~3-4 MB** for the same 17 admitted devices, a
  ~10× shrink.  At the planned 5 000-MCU scale, the repo stays in the
  hundreds-of-MB range instead of multiple GB.
* Reduces codegen cold-load time per chip by ~3-5× (the IR has fewer
  rows to instantiate; `register_fields` is a per-IP map of ~20
  entries instead of 5 936 per chip).
* Reduces extractor authoring effort: a new chip ships ~500 lines of
  YAML by hand or by a vendor pipeline that targets templates rather
  than emitting every register.
* Risk: a one-shot cutover.  The OpenSpec includes a soak phase where
  the new pipeline runs in parallel against the existing one (off
  trunk) before the v1 paths are deleted.

The full migration lands as one OpenSpec because every part is
inter-locked — half-migrating leaves the IR unable to round-trip, and
the cache + extractors broken.
