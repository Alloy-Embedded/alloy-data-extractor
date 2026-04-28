# Tasks — add-microchip-pic-extractor

## Phase 1: ATDF parser reuse (autonomous round)

- [x] 1.1 Implement `extractors/microchip_pic.py` — reuses the
      Phase 1.2 `_peripheral_records` + `_atdf_core_to_canonical`
      ATDF helpers; binds PIC8/16/18 + PIC24/dsPIC33 +
      PIC32MX/MZ/MK families.
- [x] 1.2 Discovery: `--source atdf=<path>` direct or
      `--source microchip-pic=<dfp-cache-root>` walks for the
      upper-cased device's `<DEVICE>.atdf`.
- [x] 1.3 Per-arch ATDF architecture mapping (PIC12/PIC16/PIC18/
      PIC24/dsPIC33/PIC32MX/MZ/MK) extended on the shared
      `_atdf_core_to_canonical` table.
- [x] 1.4 Per-family fallback core when ATDF omits the
      architecture attribute.

## Phase 2: Per-arch IR projection (deferred)

- [ ] 2.1 PIC8/16/18 banked-memory layout (Harvard 8-bit).
- [ ] 2.2 PIC24 + dsPIC33 indirect-addressing nuances.
- [ ] 2.3 dsPIC33 DSP-related SFR carve-outs.
- [ ] 2.4 PIC32 MIPS register carve-outs (CP0 separation).

## Phase 3: Tests

- [x] 3.1 Family resolution test for all 8 admitted PIC
      families (pic12f / pic16f / pic18 / pic24f / dspic33 /
      pic32mx / pic32mz / pic32mk).
- [x] 3.2 ATDF round-trip test (synthetic ATDF → payload).
- [x] 3.3 ATDF-arch-omitted fallback test.
- [x] 3.4 DFP-cache-root discovery test.
- [x] 3.5 Missing-source ValueError test.

## Phase 4: Bulk admission (deferred)

- [ ] 4.1 Bulk-extract PIC8/16/18 from MPLAB X DFP packs
      (~1,500 chips).
- [ ] 4.2 Bulk-extract PIC24/dsPIC33 (~500).
- [ ] 4.3 Bulk-extract PIC32MX/MZ/MK (~150).
- [ ] 4.4 YAML PRs to alloy-devices-yml.

## Phase 5: Validate + archive

- [x] 5.1 `openspec validate add-microchip-pic-extractor --strict`.
- [x] 5.2 Pytest green (177/177 + 2 skips).
- [ ] 5.3 Archive — kept open until Phase 4 lands real chips.
