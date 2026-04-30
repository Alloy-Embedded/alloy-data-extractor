# Tasks — compact-canonical-yaml-and-cache-loads

## Phase 1 — Drop never-read fields (no schema bump)

- [x] 1.1 alloy-codegen `ir/model.py`: converted
      `RouteOperation.target` to `str | None` and added
      `omit_if_empty` metadata to `target`, `value`,
      `register_peripheral`, `register_name`,
      `register_offset`, `subject_kind`, `subject_id`,
      `schema_id`.
- [x] 1.2 alloy-codegen `ir/model.py`: added `omit_if_empty`
      to `RouteRequirement.target`, `RouteRequirement.value`.
- [~] 1.3 ``RegisterFieldDescriptor.provenance`` kept
      required (Phase 2's `provenance_defaults` mechanism
      handles the size win without changing the IR contract).
- [~] 1.4 No `runtime_reports.py` change needed because the
      IR still receives a fully-populated `provenance` per
      row (expanded at parse time from the section default).
- [~] 1.5 alloy-data-extractor: extractors that build the
      payload primitives don't synthesise `route_operations`
      / `route_requirements` (those rows are produced by
      alloy-codegen's `connector_model.py`).  No extractor
      change required because the omit_if_empty flag is
      applied at the IR layer.  When the new pipeline emits
      these sections downstream, the new defaults
      automatically take effect.
- [x] 1.6 Smoke verified: every admitted YAML still loads
      cleanly via `parse_device(text)` with the new IR
      metadata, both for legacy 1.2.0 payloads (which carry
      the diagnostic strings) and for compacted 1.5.0 payloads
      (which omit them).

## Phase 2 — `provenance_defaults` per-section dedup (schema 1.5.0)

> **Pivot (during execution):** chose in-file dedup via a new
> top-level `provenance_defaults` map instead of a separate
> `<chip>.audit.yml` sidecar.  Same compaction (~30 % per chip),
> half the moving parts: codegen never deals with two files
> per chip, audit reports keep working transparently.

- [x] 2.1 alloy-codegen `bootstrap.py`: bumped
      `IR_SCHEMA_VERSION` `"1.2.0"` → `"1.5.0"`.
- [x] 2.2 alloy-codegen JSON schema (`device.schema.json`)
      already permits the new top-level field
      (`additionalProperties: true`); no edit required.
- [~] 2.3 IR row dataclasses keep `provenance: Provenance`
      required; the parse-time expand keeps the contract.
- [x] 2.4 alloy-codegen `canonical_device_yaml.py`: new
      `_compact_provenance_defaults` + `_expand_provenance_defaults`
      helpers; `serialize_device` auto-compacts and
      `parse_device` / `parse_device_payload` auto-expand.
      `provenance_defaults` added to `_TOP_LEVEL_KEY_ORDER`.
- [x] 2.5 alloy-data-extractor `emit/canonical_yaml.py`:
      mirrors the codegen helper; `serialize` runs the
      compactor before `yaml.dump`.  `SCHEMA_VERSION_CURRENT`
      bumped to `"1.5.0"`.
- [x] 2.6 alloy-codegen `runtime_reports.py`: no change
      needed — provenance is always populated post-expand.
- [x] 2.7 alloy-data-extractor pipeline writer is the writer
      that runs the compactor; nothing else to wire.
- [x] 2.8 Migration: bulk compactor
      (`scripts/compact_canonical_yamls.py`) re-emitted every
      admitted YAML in alloy-devices-yml.  Round-trip verified
      byte-for-byte after expand.  17 / 17 chips OK.

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

- [x] 4.1 Compaction sweep across all 17 admitted devices:
      55.4 MB → 30.9 MB (-44.2 %).  Per-vendor: same70
      -53 %, avr-da -52 %, imxrt -49 %, espressif -45 %,
      rp2040 -44 %, nrf52 -37 %, st -30 %.
- [x] 4.2 alloy-codegen `parse_device` smoke test on every
      vendor's compacted YAML: pin0/rf0 provenance correctly
      expanded; round-trip IR equality preserved.
- [ ] 4.3 alloy-codegen pytest run: confirm runtime tests
      still pass after schema bump + compaction +
      cache (in-flight).
- [ ] 4.4 Update CHANGELOG entries in all 3 repos.
- [ ] 4.5 `openspec validate compact-canonical-yaml-and-cache-loads --strict`
      → green; `openspec archive ...`.
- [x] 4.6 Cross-repo commits done with co-authored-by:
      * alloy-codegen `compact-canonical-yaml-and-cache-loads`
        a7583d9 + golden-fixture refresh commit (pending).
      * alloy-data-extractor
        `compact-canonical-yaml-and-cache-loads` 6faf1d0.
      * alloy-devices-yml
        `compact-canonical-yaml-and-cache-loads` 7df30e5.
