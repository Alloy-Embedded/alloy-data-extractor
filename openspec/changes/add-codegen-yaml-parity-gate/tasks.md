# Tasks — add-codegen-yaml-parity-gate

## Phase 1: IR diff helper

- [ ] 1.1 Add `alloy_codegen.testing.ir_diff(a, b) -> tuple[Diff, ...]`
      that produces a structured per-field diff between two
      `CanonicalDeviceIR` instances.
- [ ] 1.2 Diff handles tuple ordering, nested dataclass equality,
      and floating-point bit-equality.
- [ ] 1.3 Diff output is human-readable (a few lines per field).

## Phase 2: Parity test

- [ ] 2.1 Add `tests/test_yaml_parity_gate.py` parametrised over
      `bootstrap.DEVICE_REGISTRY`.
- [ ] 2.2 For each admitted device, build IR twice (legacy +
      YAML) and assert byte-equality via `ir_diff`.
- [ ] 2.3 Skip with a clear `pytest.skip(...)` when a device
      has no YAML yet (so the gate stays green during gradual
      rollout).
- [ ] 2.4 Failure mode emits the diff before raising.

## Phase 3: Fixture regeneration tool

- [ ] 3.1 Add `scripts/regen_canonical_yamls.py --device <name>`
      that re-runs the legacy path and overwrites the YAML in
      alloy-devices-yml with the freshly produced canonical
      payload.
- [ ] 3.2 Tool refuses to run unless explicitly invoked
      (no auto-fix in CI).
- [ ] 3.3 Tool writes a one-line summary identifying which
      fields changed (so reviewers can audit).

## Phase 4: Validate + archive

- [ ] 4.1 Walk all 17 admitted devices; if any diff appears,
      regenerate YAML and commit alongside this change.
- [ ] 4.2 `openspec validate add-codegen-yaml-parity-gate --strict`
- [ ] 4.3 Full pytest pass with the new gate green.
- [ ] 4.4 Archive + commit.
