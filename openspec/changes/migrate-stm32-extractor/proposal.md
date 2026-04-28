# Migrate STM32 Extraction into alloy-data-extractor

## Why

ST devices (`stm32f4`, `stm32g0` — 5 admitted devices) are
extracted by alloy-codegen's
`src/alloy_codegen/sources/cmsis_svd.py` and
`src/alloy_codegen/sources/stm32_open_pin_data.py` (~640 LOC
combined), wired through `_build_st_device_ir` in
`stages/normalize.py`.  Per the architectural pivot, vendor
parsers belong in alloy-data-extractor.  STM32 is the most
mature in-tree vendor and the natural first migration —
CMSIS-SVD is already half-done in the extractor.

## What Changes

- New extractor `alloy_data_extractor.extractors.stm32` that
  reads `STM32G071R(6-8-B)Tx.xml` (open-pin-data) plus the
  matching CMSIS-SVD file and produces canonical YAML
  byte-identical to what alloy-codegen's `_build_st_device_ir`
  emits today (verified via parity gate from `add-codegen-yaml-parity-gate`).
- Pin manifest entry for `stm32-open-pin-data` becomes
  load-bearing — the extractor reads the SHA from
  `data/source_pins.toml`.
- Re-extract all 5 admitted ST devices and overwrite their
  YAMLs in alloy-devices-yml.  Parity gate SHALL stay green.
- Delete `alloy_codegen.sources.stm32_open_pin_data` and the ST
  branches from `alloy_codegen.sources.cmsis_svd`.
- Delete `_build_st_device_ir` from
  `alloy_codegen.stages.normalize`.  ST devices SHALL flow
  exclusively through the YAML consumer.

## Impact

- alloy-data-extractor: +~640 LOC (the migrated parsers).
- alloy-codegen: -~640 LOC parser + -~150 LOC normalize plumbing.
- alloy-devices-yml: 5 YAMLs rewritten (byte-identical content
  expected; provenance updated to `source_id: stm32-extractor v1`).

## What this does NOT do

- Does not change the schema or the IR shape.
- Does not admit new ST devices.  Bulk admission is Phase 2.
- Does not migrate the modm-devices STM32 enrichment — that is
  a separate change (`migrate-modm-enrichment-extractor`).
