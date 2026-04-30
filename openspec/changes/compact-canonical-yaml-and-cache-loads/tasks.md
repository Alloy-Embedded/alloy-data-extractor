# Tasks — compact-canonical-yaml-and-cache-loads

## Phase 1 — Drop never-read fields (no schema bump)

- [ ] 1.1 alloy-codegen `ir/model.py`: convert
      `RouteOperation.target` to `str | None` and add
      `omit_if_empty` metadata to `target`, `value`,
      `register_peripheral`, `register_name`,
      `register_offset`, `subject_kind`, `subject_id`.
- [ ] 1.2 alloy-codegen `ir/model.py`: add `omit_if_empty` to
      `RouteRequirement.target`, `RouteRequirement.value`.
- [ ] 1.3 alloy-codegen `ir/model.py`: relax
      `RegisterFieldDescriptor.provenance` to
      `Provenance | None` with `omit_if_empty`; teach
      `parse_device` to back-fill the field with the top-level
      provenance bundle when it is missing.
- [ ] 1.4 alloy-codegen `runtime_reports.py`: handle
      `provenance is None` on `RegisterFieldDescriptor` rows
      gracefully (emit `audit-sidecar-missing` for that field).
- [ ] 1.5 alloy-data-extractor: stop populating the seven
      diagnostic fields above in every extractor that emits
      them (`stm32`, `cubemx`, `cmsis_svd`, `modm_devices`,
      `microchip_atdf`, `nordic_zephyr_dts`, `espressif_*`,
      `nxp_imxrt`, `raspberrypi_pico_sdk`).  Each extractor
      drops the field outright; `merge.py` no longer carries
      them through.
- [ ] 1.6 alloy-codegen + alloy-data-extractor unit tests:
      ensure round-trip on a payload that omits the dropped
      fields produces a valid IR.

## Phase 2 — Provenance audit sidecar (schema 1.5.0)

- [ ] 2.1 alloy-codegen `bootstrap.py`: bump
      `IR_SCHEMA_VERSION` `"1.4.0"` → `"1.5.0"`.
- [ ] 2.2 alloy-codegen `schema/canonical_device/*.json`:
      mark per-row `provenance` optional; add top-level
      `provenance_audit_path` (string).
- [ ] 2.3 alloy-codegen `ir/model.py`: every row dataclass
      that currently has `provenance: Provenance` becomes
      `provenance: Provenance | None` with `omit_if_empty`.
- [ ] 2.4 alloy-codegen `canonical_device_yaml.py`: new
      `serialize_device(ir)` returns
      `SerializedDevice(canonical_text, audit_text)`; new
      `parse_device(text, *, audit_text=None)` overlays the
      sidecar onto the parsed IR before returning it.
- [ ] 2.5 alloy-codegen `sources/alloy_devices_yml.py`:
      reads the sidecar from
      `<device>.audit.yml` next to the canonical YAML; passes
      it to `parse_device`.
- [ ] 2.6 alloy-codegen `runtime_reports.py`: switches to
      consuming the sidecar; falls back to top-level bundle
      when the sidecar is absent.
- [ ] 2.7 alloy-data-extractor pipeline: writes the canonical
      YAML *and* the audit sidecar atomically (both succeed
      or both rolled back).
- [ ] 2.8 Migration: re-emit every admitted device in
      `alloy-devices-yml` (vendors/{st,microchip,nordic,nxp,
      raspberrypi,espressif}).  New layout: alongside each
      `<device>.yml` ship `<device>.audit.yml`.

## Phase 3 — Binary IR cache (codegen-side)

- [x] 3.1 alloy-codegen `sources/alloy_devices_yml.py`:
      new `_cache_path` / `_load_from_cache` /
      `_write_cache_atomically` helpers.  Cache key
      `(IR_SCHEMA_VERSION, sha256(yaml_text)[:16])`; cache
      file `.cache/canonical_ir/<vendor>/<family>/<device>.<schema>.<sha8>.pkl`.
      On hit `pickle.loads` returns the IR; on miss parse +
      write atomically via `os.replace` of a sibling temp file.
- [x] 3.2 alloy-codegen: respect
      `ALLOY_CODEGEN_IR_CACHE_DIR` (path override) and
      `ALLOY_CODEGEN_IR_CACHE` (`0/false/no/off` disables).
- [x] 3.3 alloy-codegen: `.cache/` already in `.gitignore`
      (covers `.cache/canonical_ir/`).
- [x] 3.4 Smoke verified end-to-end: stm32g0b1re cold
      1051 ms → warm 2 ms (529×); atsame70q21b cold
      3608 ms → warm 106 ms (34×).  Disable env yields a
      raw-parse run.  IR equality preserved across pickle
      round-trip (`ir == cached_ir`).
- [ ] 3.5 Add pytest under `tests/test_canonical_ir_cache.py`:
      cache hit returns identical IR, cache write atomicity,
      schema-bump invalidation (mock `IR_SCHEMA_VERSION`),
      env-var disable, edited-YAML invalidation.

## Phase 4 — Validation, measurement, archive

- [ ] 4.1 Re-emit ST corpus, capture before/after byte sizes
      + parse times.  Record in `design.md`.
- [ ] 4.2 Bulk-admit a handful of vendors (Microchip SAM,
      Espressif, Nordic, NXP) end-to-end to confirm the
      pipeline writes valid sidecars.
- [ ] 4.3 `alloy-codegen` pytest run: confirm runtime
      tests still pass.
- [ ] 4.4 Update CHANGELOG entries in all 3 repos
      (alloy-codegen, alloy-data-extractor,
      alloy-devices-yml).
- [ ] 4.5 `openspec validate compact-canonical-yaml-and-cache-loads --strict`
      → green; `openspec archive ... --skip-specs`.
- [ ] 4.6 Cross-repo commits with co-authored-by on
      alloy-codegen, alloy-data-extractor,
      alloy-devices-yml.
