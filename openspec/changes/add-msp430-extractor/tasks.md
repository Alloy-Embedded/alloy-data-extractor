# Tasks — add-msp430-extractor

## Scaffold (autonomous round)

- [x] S.1 Register `msp430` Extractor for `(ti, msp430)`.
- [x] S.2 Wire scaffold into `pipeline.py` side-effect imports.
- [x] S.3 Test scaffold resolution + NotImplementedError shape.

## Phase 1: Implementation

- [ ] 1.1 Implement `extractors/msp430.py` parsing TI SysConfig +
      MSP430 device-headers.
- [ ] 1.2 Schema: add `msp430` to `identity.core` accepted values.
- [ ] 1.3 Pin entry `ti-msp430-headers` with origin URL + license.
- [ ] 1.4 Bulk extract a representative slice (~20 chips per series).
- [ ] 1.5 Per-series YAML PRs to alloy-devices-yml.
- [ ] 1.6 `openspec validate add-msp430-extractor --strict`.
- [ ] 1.7 Archive + commit.
