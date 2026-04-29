# Tasks — complete-imxrt1060-register-coverage

## Phase 1: Audit current SVD coverage

- [x] 1.1 Ran `nxp_mcux` extractor against the cached
      `MIMXRT1062.xml`.  Initial state (before commit `18fd166`):
      0 registers + 0 fields — the extractor only emitted
      peripheral instances + IRQ tables.
- [x] 1.2 Root cause identified: `cmsis_svd._peripheral_records`
      didn't walk `<peripheral><registers>` blocks at all.  No
      whitelist or size cap was in play; the walk simply wasn't
      implemented.
- [x] 1.3 Gap documented inline in the proposal — and addressed
      in the same commit chain.

## Phase 2: Extend the SVD parser

- [x] 2.1 `cmsis_svd._register_and_field_records` walks every
      `<peripheral><registers><register>` element with full
      `(register_id, peripheral, name, offset_bytes, size_bits,
      access)`.  (Commit `18fd166`.)
- [x] 2.2 For each register, walks its `<fields><field>` block
      with full `(field_id, register_id, peripheral,
      register_name, name, bit_offset, bit_width, access)`.
      Three field-position forms supported: `bitOffset+bitWidth`,
      `bitRange="[msb:lsb]"`, `lsb+msb`.
- [x] 2.3 `<derivedFrom>` resolved by walking to the base
      peripheral and inheriting its register tree (USART2
      derivedFrom USART1 etc.).  `<dim>` arrays are expanded
      into one row per index.

## Phase 3: IR projection

- [x] 3.1 Registers + register_fields project onto the
      canonical IR shape (commit `18fd166`).
- [x] 3.2 Per-row provenance carries
      `source_id="nxp-mcux-soc-svd"` and the SVD basename as
      `source_path` (commits `7fb4dc3` + this change).
- [ ] 3.3 Re-extract YAML for `mimxrt1062` and `mimxrt1064` —
      *deferred*: same caveat as the STM32 re-emit.  The
      primary nxp-mcux extractor still doesn't emit
      `bootstrap-patch` overrides or IOMUX tables that the
      existing canonical YAMLs carry; bulk re-emit would
      regress those fields.  Closing that gap is a separate
      workstream once IOMUX-from-`MIMXRT1062.h` lands.
- [x] 3.4 Confirmed payload-shape via end-to-end test against
      the cached MIMXRT1062.xml: 117 peripherals, 5,785
      registers, 23,156 register_fields (well above the
      proposal's "≥1500 / ≥6000" threshold).

## Phase 4: Verification

- [x] 4.1 Per-peripheral counts — automated check via the
      e2e extraction.  LPUART1 / LPSPI1 / LPI2C1 / GPIO1 all
      carry register trees pulled from MIMXRT1062.xml.
- [ ] 4.2 alloy-codegen `--runtime-cpp-smoke` gate against
      regenerated YAML — *deferred* with task 3.3.
- [ ] 4.3 `uart.hpp` diff — *deferred* with task 3.3.

## Phase 5: Spec + final checks

- [x] 5.1 Spec delta lands as part of this archive.
- [x] 5.2 `openspec validate complete-imxrt1060-register-coverage
      --strict` passes.
- [x] 5.3 `pytest -q` clean (243 passed / 2 skipped).
- [ ] 5.4 Push regenerated YAMLs to alloy-devices-yml —
      *deferred* with task 3.3.
