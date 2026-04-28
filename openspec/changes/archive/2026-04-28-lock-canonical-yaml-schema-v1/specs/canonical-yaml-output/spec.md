## ADDED Requirements

### Requirement: Every canonical-device YAML SHALL carry a `schema_version` matching the bundled schema

Every YAML written by the extractor or committed to alloy-devices-yml SHALL declare a top-level `schema_version` field whose value is a semver string matching the schema currently bundled in alloy-devices-yml.  The extractor's `write_device_yaml(...)` SHALL refuse to write a payload that does not satisfy this rule.  alloy-codegen's YAML consumer SHALL refuse to load any YAML whose `schema_version` major component differs from the codegen's pinned major (`alloy_codegen.bootstrap.IR_SCHEMA_MAJOR`).

#### Scenario: Writing a payload without schema_version raises

- **WHEN** `write_device_yaml(payload={"identity": {...}}, ...)` is called
- **THEN** the writer SHALL raise `ValueError` whose message names the missing field
- **AND** no file SHALL be written

#### Scenario: Loading a YAML with a future major version is rejected

- **WHEN** alloy-codegen loads a YAML whose `schema_version` is `2.0.0` while `IR_SCHEMA_MAJOR == 1`
- **THEN** the loader SHALL raise `IRSchemaVersionMismatch`
- **AND** the error SHALL list the loaded major and the codegen's pinned major

### Requirement: Every committed YAML in alloy-devices-yml SHALL validate against `device.schema.json`

The alloy-devices-yml CI workflow SHALL fail any PR that introduces or modifies a YAML under `vendors/**/devices/*.yml` if that YAML does not validate against `schema/canonical_device/device.schema.json` using JSON Schema 2020-12.

#### Scenario: Adding an invalid YAML fails CI

- **WHEN** a PR adds `vendors/foo/bar/devices/baz.yml` missing the required `identity.core` field
- **THEN** the validation job SHALL fail with a structured error listing `identity/core: required field`
- **AND** the PR SHALL be blocked from merging

### Requirement: Schema version bumps SHALL follow a documented semver rule

The schema's version field SHALL evolve under semver: PATCH bumps are purely additive optional fields (existing YAMLs continue to validate); MINOR bumps add required fields with a documented backfill path; MAJOR bumps are incompatible restructurings that require coordinated bumps in extractor + codegen.

#### Scenario: A PATCH bump leaves all existing YAMLs valid

- **WHEN** the schema bumps from `1.2.0` to `1.2.1` by adding a new optional `identity.silicon_rev` field
- **THEN** every YAML in `vendors/**/devices/*.yml` SHALL still validate against the new schema without modification
