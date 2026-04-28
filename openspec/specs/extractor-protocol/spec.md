# extractor-protocol Specification

## Purpose
TBD - created by archiving change define-extractor-protocol. Update Purpose after archive.
## Requirements
### Requirement: Every extractor SHALL conform to a single Python Protocol

The extractor package SHALL ship a single `Extractor` Protocol in `alloy_data_extractor.extractor_protocol`.  Every concrete extractor (CMSIS-SVD, Zephyr DTS, ATDF, MCUXpresso, ESP-IDF, Pico SDK, MPLAB DFP, …) SHALL register itself via `@register_extractor(...)` and SHALL expose an `extract(request: ExtractionRequest) -> ExtractionResult` method.  The pipeline SHALL dispatch generically via `resolve_extractor(vendor, family)` — no per-vendor `if` cascades in the pipeline module.

#### Scenario: Adding a new extractor requires no pipeline edits

- **WHEN** a contributor adds a new extractor module that uses `@register_extractor("foo", vendors=("foo-vendor",), families=("foo-family",))`
- **THEN** `resolve_extractor("foo-vendor", "foo-family")` SHALL return that extractor without any edit to `pipeline.py`
- **AND** the CLI's `--extractor` flag SHALL list `foo` automatically

#### Scenario: Resolving an unsupported (vendor, family) raises a clear error

- **WHEN** `resolve_extractor("not-a-vendor", "not-a-family")` is called
- **THEN** the function SHALL raise `ValueError`
- **AND** the message SHALL list every (vendor, family) pair currently registered

### Requirement: Extractor input and output SHALL be uniformly typed

Every extractor SHALL accept a single `ExtractionRequest` dataclass (with `vendor`, `family`, `device`, `source_paths: dict[str, Path]`, `revision`, `extra: dict[str, Any]`) and SHALL return a single `ExtractionResult` (with `payload: dict`, `provenance: ProvenanceRecord`, `warnings: tuple[str, ...]`).  Source-format-specific parameters (e.g. `svd_path`, `dts_path`, `atdf_path`) SHALL flow through `ExtractionRequest.source_paths` keyed by source-id.

#### Scenario: Source paths are addressed by source-id, not positional

- **WHEN** the CLI is invoked with `--source cmsis-svd=/path/to/foo.svd`
- **AND** the resolved extractor calls `request.source_paths["cmsis-svd"]`
- **THEN** the extractor SHALL receive the path
- **AND** an extractor that asks for a key not present SHALL raise `MissingSourceError` whose message names the missing key

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

