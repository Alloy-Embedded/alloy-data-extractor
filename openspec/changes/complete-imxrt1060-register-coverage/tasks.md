# Tasks — complete-imxrt1060-register-coverage

## Phase 1: Audit current SVD coverage

- [ ] 1.1 Run `nxp_mcux` extractor against the bundled
      `MIMXRT1062.svd` fixture.  Compare register counts per
      peripheral: emitted vs SVD source.
- [ ] 1.2 Identify the filter / whitelist that's dropping
      registers.  Either (a) a hardcoded peripheral whitelist,
      (b) a register-name regex, or (c) a register-size cap.
- [ ] 1.3 Document the gap — file an issue noting "extractor
      drops X% of SVD registers".

## Phase 2: Extend the SVD parser

- [ ] 2.1 Walk every `<peripheral><registers><register>` element
      in the SVD; build one `RegisterDescriptor` per register
      with full `(peripheral, name, offset, access, size_bits,
      base_address)`.
- [ ] 2.2 For each register, walk its `<fields><field>` block;
      build one `RegisterFieldDescriptor` per field with
      `(peripheral, register_name, name, bit_offset, bit_width,
      access)`.
- [ ] 2.3 Skip registers tagged `<derivedFrom>` (re-use the
      base register's fields rather than duplicating).

## Phase 3: IR projection

- [ ] 3.1 Project the parsed registers onto the canonical IR's
      `device.registers` and `device.register_fields` tuples.
- [ ] 3.2 Tag every entry's provenance with
      `source_id="nxp-mcux-soc-svd"` and the SVD revision SHA.
- [ ] 3.3 Re-extract YAML for `mimxrt1062` and `mimxrt1064`.
- [ ] 3.4 Confirm the resulting YAMLs round-trip to a
      schema-valid `CanonicalDeviceIR` with the expected
      register density (>= ~30 registers / peripheral).

## Phase 4: Verification

- [ ] 4.1 Per-peripheral spot-check: for LPUART1, LPSPI1,
      LPI2C1, GPIO1 — confirm every register in the SVD shows
      up in the YAML with the right offset.
- [ ] 4.2 Run alloy-codegen's `--runtime-cpp-smoke` gate on
      mimxrt1062 to confirm the regenerated YAML still
      produces a compiling C++ contract.
- [ ] 4.3 Diff `uart.hpp` before vs after — every
      `kInvalidRegisterRef` for the LPUART traits should now
      resolve to a real register reference.

## Phase 5: Spec + final checks

- [ ] 5.1 Spec delta in
      `specs/vendor-coverage/spec.md` — nxp_mcux extractor
      SHALL project every SVD-defined register + field.
- [ ] 5.2 `openspec validate
      complete-imxrt1060-register-coverage --strict` passes.
- [ ] 5.3 `pytest -q` + `ruff check` clean.
- [ ] 5.4 Push regenerated YAMLs to alloy-devices-yml.
