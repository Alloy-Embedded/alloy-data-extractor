# Tasks — add-microchip-pic-extractor

## Phase 1: PIC8/16/18 (~1,500 chips)

- [ ] 1.1 Implement `extractors/microchip_dfp/pic.py` (Harvard 8-bit).
- [ ] 1.2 Discover via cmsis-pack-manager / MPLAB X DFP packs.
- [ ] 1.3 Bulk-extract; commit one big YAML batch.

## Phase 2: PIC24 + dsPIC33 (~500)

- [ ] 2.1 Implement `extractors/microchip_dfp/pic24.py` (16-bit
      modified Harvard).
- [ ] 2.2 Bulk-extract.

## Phase 3: PIC32 (~150)

- [ ] 3.1 Implement `extractors/microchip_dfp/pic32.py` (MIPS).
- [ ] 3.2 Bulk-extract MX, MZ, MK families.

## Phase 4: Schema + tests

- [ ] 4.1 Extend `device.schema.json` `identity.core` enum with
      PIC variants (`pic18`, `pic16f`, `pic12f`, `pic24f`,
      `dspic33`, `pic32mx`, `pic32mz`, `pic32mk`).
- [ ] 4.2 Per-arch unit tests on a representative chip per family.
- [ ] 4.3 `openspec validate add-microchip-pic-extractor --strict`.
- [ ] 4.4 Archive + commit (likely multiple PRs).
