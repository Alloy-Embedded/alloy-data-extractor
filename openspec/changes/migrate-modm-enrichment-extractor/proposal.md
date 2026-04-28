# Migrate modm-devices Enrichment into alloy-data-extractor

## Why

`alloy-codegen/src/alloy_codegen/sources/modm_devices.py` (529
LOC) parses the modm-devices XML catalog and *enriches* an
already-built canonical IR with DMA + clock + alternate-function
data that CMSIS-SVD does not carry.  It is invoked by
`stages/normalize.py` for STM32 devices only.

modm-devices is a cross-source enrichment, not a primary
extractor — but it is still a vendor-source parser, and per the
architectural pivot it belongs in alloy-data-extractor.  More
importantly, the proper place for "merge facts from multiple
sources for the same chip" is the `add-cross-source-merge`
infrastructure (Phase 2.2).  This change pre-migrates the modm
parser so it slots into that infrastructure when it lands.

## What Changes

- New extractor `alloy_data_extractor.extractors.modm_devices`
  registered as a *secondary* extractor: it does not produce a
  canonical YAML on its own; it reads modm XML and produces an
  enrichment record consumed by the merge stage.
- Until the merge stage exists (Phase 2.2), the STM32 extractor
  (`migrate-stm32-extractor`) calls modm directly to compose its
  output — this is documented as transitional plumbing and
  removed when 2.2 lands.
- alloy-codegen: delete `sources/modm_devices.py`.  Strip the
  modm-import call from `_build_st_device_ir` (already removed
  by 1.1, so this is just cleanup of the codegen-side imports
  if any survived).

## Impact

- alloy-data-extractor: +~529 LOC.
- alloy-codegen: -~529 LOC.
- alloy-devices-yml: STM32 YAMLs may gain a richer
  `dma_bindings` / `clock_nodes` surface (whatever modm fills
  in) — gated by parity expectations from
  `add-codegen-yaml-parity-gate`.

## What this does NOT do

- Does not implement cross-source merge generally.  That is
  Phase 2.2.
- Does not extend modm coverage to vendors beyond STM32 (modm
  has SAM data too; deferred to a follow-up).
