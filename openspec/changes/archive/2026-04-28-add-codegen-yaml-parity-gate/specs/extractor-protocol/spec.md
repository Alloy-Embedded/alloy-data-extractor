## ADDED Requirements

### Requirement: Codegen SHALL prove YAML/legacy IR parity for every admitted device

alloy-codegen SHALL ship a parity gate (`tests/test_yaml_parity_gate.py`) that for every device in `bootstrap.DEVICE_REGISTRY` builds the canonical IR twice — once via the legacy `_build_<vendor>_device_ir` path and once via `alloy_devices_yml.load_canonical_device(...)` — and asserts the two IR instances are byte-identical.  The gate SHALL run as part of the regular pytest suite and SHALL be a hard CI failure on drift.

#### Scenario: Drift on any admitted device fails the gate

- **WHEN** the legacy path produces an IR with `peripherals[3].dma_bindings == (...)` but the YAML path loads `peripherals[3].dma_bindings == ()`
- **THEN** the parity test for that device SHALL fail
- **AND** the failure message SHALL include the structured diff identifying `peripherals[3].dma_bindings` as the drifted field

#### Scenario: Devices without YAML are skipped, not failed

- **WHEN** an admitted device has no `vendors/<v>/<f>/devices/<d>.yml` in alloy-devices-yml yet
- **THEN** the parity test for that device SHALL skip with a clear message
- **AND** the rest of the gate SHALL continue green

### Requirement: Fixture regeneration SHALL be a deliberate, human-invoked action

When the legacy path is intentionally changed (e.g. an emitter fix that affects the IR), the YAML SHALL be regenerated via an explicit `scripts/regen_canonical_yamls.py --device <name>` invocation; the parity gate SHALL NEVER auto-fix YAMLs in CI.

#### Scenario: CI never silently rewrites YAMLs

- **WHEN** the parity gate detects drift in CI
- **THEN** the gate SHALL fail
- **AND** SHALL NOT modify any YAML in alloy-devices-yml
- **AND** SHALL emit a message instructing the maintainer to run `scripts/regen_canonical_yamls.py` locally and review the diff
