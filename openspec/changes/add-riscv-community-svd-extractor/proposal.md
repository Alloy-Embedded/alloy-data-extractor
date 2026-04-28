# Add Community RISC-V SVD Extractor

## Why

Beyond Espressif's RISC-V variants (already covered via
`migrate-espressif-esp-idf-extractor`), there is a long tail of
community RISC-V MCUs with maintained SVDs but no presence in
any OSS HAL framework: GD32V (GigaDevice, ~10 chips), BL602/702
(Bouffalo, ~5), CH32V (WCH, ~30), K210 + K230 (Kendryte, ~5),
Allwinner D1 / Pine64, etc.  Total: ~80 chips.

These vendors all publish CMSIS-SVD-compatible XML.  The extractor
only needs a thin per-vendor adapter on top of the existing
CMSIS-SVD extractor — no new parser.

## What Changes

- Per-vendor registry entries for `gigadevice`, `bouffalo`,
  `wch`, `kendryte`, `allwinner` covering their RISC-V families.
- Extractors are thin shims registering the existing CMSIS-SVD
  extractor against the vendor's families — implementation is
  pure metadata.
- Schema enum addition: `identity.core` accepts
  `riscv-rv32imac`, `riscv-rv32imc`, `riscv-rv32imafc`,
  `riscv-rv64gc`.
- Pin entries for each community SVD repo.

## Impact

- alloy-data-extractor: +~200 LOC (mostly per-vendor metadata).
- alloy-devices-yml: +~80 YAMLs.
- The project gains the broadest OSS RISC-V MCU coverage.

## What this does NOT do

- Does not target SiFive HiFive boards (those are application-class
  Linux SoCs, out of scope).
- Does not implement application-class RISC-V (RV64GC with MMU).
- Does not write codegen-side emitters for any of these.
