# Migrate Microchip DFP Extraction into alloy-data-extractor

## Why

`alloy-codegen/src/alloy_codegen/sources/microchip_dfp.py`
(1,053 LOC — the heaviest single file in `sources/`) parses
Microchip ATDF packs and feeds 3 admitted devices: `avr-da`
(AVR8) and `same70` (Cortex-M7F, 2 variants).  This is the
biggest single migration in Phase 1 and unblocks the eventual
PIC extractor (Phase 3.1) which reuses the same DFP/`.atpack`
infrastructure.

## What Changes

- New extractor `alloy_data_extractor.extractors.microchip_dfp`
  covering `(microchip, avr-da)` and `(microchip, same70)`.
- ATDF XML parsing logic ported wholesale; module helpers split
  into `microchip_dfp/atdf.py` (XML parser) +
  `microchip_dfp/avr.py` + `microchip_dfp/sam.py` (per-arch IR
  projection) so the eventual PIC extractor can reuse `atdf.py`.
- Same70 PWM / AVR-DA TCA peripherals continue to be emitted
  byte-identical to today.
- alloy-codegen `sources/microchip_dfp.py` deleted.
  `_build_microchip_device_ir` and `_build_avr_da_device_ir`
  removed from `stages/normalize.py`.
- `_build_same70_pwm_peripherals` (used by the same70 IR build)
  ported into the extractor as a module-internal helper.

## Impact

- alloy-data-extractor: +~1,053 LOC (split across 3 modules).
- alloy-codegen: -~1,053 LOC parser + -2 normalize entry points.
- alloy-devices-yml: 3 YAMLs rewritten byte-identical
  (avr128da32, atsame70n21b, atsame70q21b).
- Unblocks `add-microchip-pic-extractor` (Phase 3.1) since the
  ATDF/DFP plumbing is now in the extractor.

## What this does NOT do

- Does not admit any PIC devices (that is `add-microchip-pic-extractor`).
- Does not change the IR shape or YAML schema.
