# Tasks — migrate-microchip-dfp-extractor

## Phase 1: Port + restructure

- [ ] 1.1 Copy `microchip_dfp.py` (1,053 LOC) to extractor.
- [ ] 1.2 Split into `extractors/microchip_dfp/{__init__.py,atdf.py,avr.py,sam.py}`.
- [ ] 1.3 `atdf.py` carries the XML parsing — must be reusable
      for PIC packs (Phase 3.1).
- [ ] 1.4 Register `Extractor` for `(microchip, avr-da)` and
      `(microchip, same70)`.

## Phase 2: Re-extract

- [ ] 2.1 Run extractor against avr128da32, atsame70n21b, atsame70q21b.
- [ ] 2.2 Diff vs existing YAMLs — drift SHALL be zero.
- [ ] 2.3 Same70 PWM peripherals must round-trip identically.

## Phase 3: Cleanup

- [ ] 3.1 Confirm parity gate green for both families.
- [ ] 3.2 Delete `alloy_codegen/sources/microchip_dfp.py`.
- [ ] 3.3 Delete `_build_microchip_device_ir` + `_build_avr_da_device_ir`
      + `_build_same70_pwm_peripherals` from normalize.

## Phase 4: Validate + archive

- [ ] 4.1 Both repos green pytest, parity gate green.
- [ ] 4.2 `openspec validate migrate-microchip-dfp-extractor --strict`.
- [ ] 4.3 Archive + commit.
