# Add 8051 Extractor

## Why

Modern 8051 derivatives (Nuvoton N76, SiLabs EFM8, STC15W,
etc.) ship in millions of units — heavy in low-cost consumer
electronics.  No OSS HAL framework covers them.  Each vendor
publishes register definitions in their SDK headers and
datasheets.  This is the lowest-priority stretch, opportunistic
contributor work.

## What Changes

- New extractor `alloy_data_extractor.extractors.intel_8051`
  parsing vendor SDK headers (Nuvoton, SiLabs, STC).
- Schema gains `identity.core: i8051` (Intel 8051 / MCS-51 ISA).
- Per-vendor pin entries.

## Impact

- alloy-data-extractor: +~600 LOC (per-vendor variability).
- alloy-devices-yml: +~150 YAMLs.
- Codegen-side: 8051 emit support is its own deferred problem;
  YAML coverage is independent.

## What this does NOT do

- Does not implement application-class architectures.
- Does not generate 8051 C code (would require sdcc-tooled
  emitter — out of scope for foreseeable future).
