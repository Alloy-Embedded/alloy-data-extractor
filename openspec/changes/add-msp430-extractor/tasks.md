# Tasks — add-msp430-extractor

## Phase 1: Header parser (autonomous round)

- [x] 1.1 Implement `extractors/msp430.py` parsing the
      MSP430 vendor header `#define <NAME>_ 0x<addr>` style
      with macro-dereference forms skipped.
- [x] 1.2 Project SFRs into canonical-payload shape:
      peripherals (grouped by port / USCI / generic prefix) +
      registers.
- [x] 1.3 `identity.core: msp430` set explicitly (no schema bump).
- [x] 1.4 Tests: regex coverage, dedup, port grouping (P1*),
      USCI grouping (UCA0*), missing-source ValueError, frozen
      dataclass, end-to-end payload shape.

## Phase 2: Implementation extensions

- [ ] 2.1 16-bit register width inference (e.g. TAR / TACCR0).
- [ ] 2.2 Pin-multiplexing tables (P1SEL / P1SEL2 → AF
      mapping projection).
- [ ] 2.3 Pin entry `ti-msp430-headers` with origin URL.
- [ ] 2.4 Bulk-extract a representative slice (~20 chips per
      series) and commit YAMLs to alloy-devices-yml.

## Phase 3: Validate + archive

- [x] 3.1 `openspec validate add-msp430-extractor --strict`.
- [x] 3.2 Pytest green (165/165 + 2 skips).
- [ ] 3.3 Archive — kept open until Phase 2 + at least one
      MSP430 chip lands in alloy-devices-yml.
