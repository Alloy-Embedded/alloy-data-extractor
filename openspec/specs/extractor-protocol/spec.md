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

