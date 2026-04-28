# Add Microchip PIC Extractor (PIC8/16/18/24/32 + dsPIC)

## Why

This is the **moat-defining feature** of the project.  No
existing OSS HAL framework — modm, Embassy, Zephyr (HAL), TinyGo,
Rust embedded-hal — covers PIC.  Microchip publishes the full
DFP (Device Family Pack) format for every PIC family they sell:
PIC8/16/18 (~1,500 chips), PIC24 + dsPIC33 (~500), PIC32MX/MZ/MK
(~150).  Total: ~2,150 chips, all with machine-readable register
data.

`migrate-microchip-dfp-extractor` (Phase 1.2) already split the
ATDF parser into a reusable `atdf.py` module.  This change reuses
that infrastructure to admit PIC.

## What Changes

- Per-arch IR projection: `extractors/microchip_dfp/pic.py`
  (PIC8/16/18 — Harvard, single accumulator),
  `extractors/microchip_dfp/pic24.py` (PIC24/dsPIC — modified
  Harvard, 16-bit), `extractors/microchip_dfp/pic32.py`
  (MIPS-based — completely different architecture).
- Register `Extractor` for every PIC family discovered in the
  pinned MPLAB X DFP catalog.  Bulk discovery (Phase 2.1)
  fans them out automatically.
- New core values in canonical YAML schema: `pic18`, `pic16f`,
  `pic12f`, `pic24f`, `dspic33`, `pic32mx`, `pic32mz`, `pic32mk`.
- alloy-devices-yml: gain ~2,150 YAMLs in one PR (likely split
  per family for review tractability).
- alloy-codegen: PIC families admitted incrementally — codegen
  emits C++ headers per family as emitter coverage extends.
  YAML existence does NOT imply codegen emits artifacts;
  emitter admission is a separate codegen-side decision.

## Impact

- alloy-data-extractor: +~1,500 LOC across 3 arch modules.
- alloy-devices-yml: +~2,150 YAMLs (~MB-scale repo growth).
- Public positioning: alloy becomes the **only multi-arch OSS
  framework covering PIC + AVR + ARM + RISC-V + Xtensa**.

## What this does NOT do

- Does not generate C++ HAL for PIC.  Codegen-side admission is
  scoped per family in alloy-codegen and may stay deferred.
- Does not target 8-bit PICs older than baseline PIC10F (no DFP).
