# Tasks — add-8051-extractor

## Phase 1: SFR header parser (autonomous round)

- [x] 1.1 Implement `extractors/intel_8051.py` parsing
      SDCC-flavored 8051 SFR headers (`__sfr __at (0x80) P0;`,
      `__sbit`, `sfr16`).
- [x] 1.2 Project SFRs into canonical-payload shape: peripherals
      (grouped by name prefix) + registers (one per SFR).
- [x] 1.3 `identity.core: i8051` set explicitly.
- [x] 1.4 Tests: header-format variants (Nuvoton/SDCC), sbit
      handling, sfr16 width detection, dedup, missing-source
      ValueError, family resolution across Nuvoton N76/N79,
      SiLabs EFM8, STC STC15W.

## Phase 2: Implementation extensions

- [ ] 2.1 Bank-switching SFR layout (used by N76 / N79
      extended-RAM access).
- [ ] 2.2 Indirect-addressing register declarations.
- [ ] 2.3 Bulk-extract one chip per vendor with vendor-supplied
      headers; commit YAMLs.

## Phase 3: Validate + archive

- [x] 3.1 `openspec validate add-8051-extractor --strict`.
- [x] 3.2 Pytest green (156/156 + 2 skips).
- [ ] 3.3 Archive — kept open until Phase 2 + at least one
      vendor's chips are committed to alloy-devices-yml.
