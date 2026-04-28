# Tasks — add-8051-extractor

## Scaffold (autonomous round)

- [x] S.1 Register `intel-8051` Extractor for Nuvoton N76/N79,
      SiLabs EFM8, STC STC15W families.
- [x] S.2 Wire scaffold into `pipeline.py` side-effect imports.
- [x] S.3 Test scaffold resolution + NotImplementedError shape.

## Phase 1: Implementation

- [ ] 1.1 Implement `extractors/intel_8051.py` parsing per-vendor
      SDK headers (Nuvoton, SiLabs EFM8, STC).
- [ ] 1.2 Schema bump: add `i8051` to `identity.core` enum.
- [ ] 1.3 Bulk-extract one chip per vendor; validate.
- [ ] 1.4 `openspec validate add-8051-extractor --strict`.
- [ ] 1.5 Archive + commit.
