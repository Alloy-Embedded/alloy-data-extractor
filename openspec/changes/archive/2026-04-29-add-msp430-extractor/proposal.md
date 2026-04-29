# Add MSP430 Extractor

## Why

TI MSP430 is the canonical 16-bit ultra-low-power MCU family
(~200 chips).  No OSS HAL framework covers it.  TI publishes
header files + linker scripts + SysConfig metadata for every
MSP430 device.  Adding MSP430 to alloy is a natural fit once
the extractor pipeline matures.

## What Changes

- New extractor `alloy_data_extractor.extractors.msp430` that
  consumes TI SysConfig data + MSP430 device-header files.
- Schema gains `identity.core: msp430` (16-bit von Neumann ISA).
- Pin entry `ti-msp430-headers` in `data/source_pins.toml`.
- Bulk discovery enumerates the MSP430 catalog from TI's
  CMSIS-Pack mirror or the SysConfig metadata.

## Impact

- alloy-data-extractor: +~400-600 LOC.
- alloy-devices-yml: +~200 YAMLs (one PR per series ideally).
- Codegen-side admission is independent — emitter coverage for
  MSP430 may stay deferred indefinitely.

## What this does NOT do

- Does not implement MSP432 (those are Cortex-M4 and would go
  through CMSIS-SVD / cmsis-pack-manager bulk discovery).
- Does not generate MSP430 C code.  YAML coverage only.
