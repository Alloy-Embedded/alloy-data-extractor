# Migrate NXP MCUXpresso Extraction into alloy-data-extractor

## Why

`alloy-codegen/src/alloy_codegen/sources/nxp_mcux.py` (243 LOC)
parses NXP MCUXpresso SDK headers and feeds 2 admitted iMXRT
devices (`mimxrt1062`, `mimxrt1064`).  Per the architectural
pivot, vendor parsers belong in alloy-data-extractor.

## What Changes

- New extractor `alloy_data_extractor.extractors.nxp_mcux`
  registered for `(nxp, imxrt1060)`.
- Logic ported wholesale; provenance updated to
  `source_id: nxp-mcuxpresso-sdk` + revision from
  `data/source_pins.toml`.
- alloy-codegen `sources/nxp_mcux.py` deleted.
  `_build_nxp_device_ir` removed from `stages/normalize.py`.

## Impact

- alloy-data-extractor: +~243 LOC.
- alloy-codegen: -~243 LOC parser.
- alloy-devices-yml: 2 YAMLs rewritten byte-identical.

## What this does NOT do

- Does not extend coverage to LPC, Kinetis, or MCX (those land
  in `add-bulk-discovery-cmsis-pack-manager` Phase 2.1).
- Does not change IR shape.
