# Tasks — add-codegen-yaml-parity-gate

## Phase 1: IR diff helper

- [x] 1.1 Add `alloy_codegen.testing.ir_diff(a, b) -> tuple[Diff, ...]`
      that produces a structured per-field diff between two
      `CanonicalDeviceIR` instances.
- [x] 1.2 Diff handles tuple ordering, nested dataclass equality,
      and floating-point bit-equality.
- [x] 1.3 Diff output is human-readable (a few lines per field).

## Phase 2: Parity test

- [x] 2.1 Add `tests/test_yaml_parity_gate.py` parametrised over
      `bootstrap.DEVICE_REGISTRY`.
- [x] 2.2 For each admitted device, build IR twice (legacy +
      YAML) and assert byte-equality via `ir_diff`.
- [x] 2.3 Skip with a clear `pytest.skip(...)` when a device
      has no YAML yet (so the gate stays green during gradual
      rollout).
- [x] 2.4 Failure mode emits the diff before raising.

## Phase 3: Fixture regeneration tool

- [x] 3.1 Add `scripts/regen_canonical_yamls.py --device <name>`
      that re-runs the legacy path and overwrites the YAML in
      alloy-devices-yml with the freshly produced canonical
      payload.
- [x] 3.2 Tool refuses to run unless explicitly invoked
      (no auto-fix in CI).
- [x] 3.3 Tool writes a one-line summary identifying which
      fields changed (so reviewers can audit).

## Phase 4: Validate + archive

- [x] 4.1 Walk all 17 admitted devices; if any diff appears,
      regenerate YAML and commit alongside this change.
- [x] 4.2 `openspec validate add-codegen-yaml-parity-gate --strict`
- [x] 4.3 Full pytest pass with the new gate green.
- [x] 4.4 Archive + commit.
