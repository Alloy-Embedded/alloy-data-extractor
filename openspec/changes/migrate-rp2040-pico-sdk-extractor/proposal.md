# Migrate RP2040 Pico SDK Extraction into alloy-data-extractor

## Why

`alloy-codegen/src/alloy_codegen/sources/pico_sdk.py` (182 LOC)
parses Pico SDK headers and feeds 2 admitted RP2040 devices
(`pico`, `rp2040`).  Per the architectural pivot, vendor parsers
belong in alloy-data-extractor.  RP2040 is the only Cortex-M0+
dual-core in the admitted set.

## What Changes

- New extractor `alloy_data_extractor.extractors.pico_sdk`
  registered for `(raspberrypi, rp2040)`.
- Dual-core single-core-perspective bring-up (core 0 only)
  preserved; core-1 bring-up + FIFO/spinlock primitives remain
  deferred (per existing alloy-devices README carve-out).
- alloy-codegen: delete `sources/pico_sdk.py` and
  `_build_rp2040_device_ir`.

## Impact

- alloy-data-extractor: +~182 LOC.
- alloy-codegen: -~182 LOC.
- alloy-devices-yml: 2 YAMLs rewritten byte-identical.
- Pico SDK pin (`raspberrypi-pico-sdk` in `data/source_pins.toml`)
  becomes load-bearing.

## What this does NOT do

- Does not implement RP2350.  RP2350 lands as a separate
  admission once an extractor extension covers Cortex-M33.
- Does not solve the dual-core inter-core IPC primitives.
