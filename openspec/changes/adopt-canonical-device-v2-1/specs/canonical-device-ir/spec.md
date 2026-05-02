# Spec — Canonical Device IR (adopt v2.1, retire v1)

## ADDED Requirements

### Requirement: The canonical device YAML SHALL declare schema "alloy.device.v2.1" exactly

Every canonical YAML in `alloy-devices-yml` SHALL declare its top-level
`schema:` key as the string literal `"alloy.device.v2.1"`.  The legacy
`schema_version: "1.x.y"` semver field SHALL NOT appear in any new
file.  Codegen consumers SHALL match the constant exactly — there is
no major-version compatibility window.

#### Scenario: parse_device rejects v1 payload

- **GIVEN** a YAML payload that declares `schema_version: "1.5.0"`
  (the previous v1 schema bump)
- **WHEN** alloy-codegen calls `parse_device(text)`
- **THEN** the call SHALL raise `StageExecutionError`
- **AND** the error message SHALL identify the legacy schema and
  point at the v2.1 cutover migration note

#### Scenario: parse_device accepts the canonical v2.1 form

- **GIVEN** a YAML whose top-level `schema:` value is
  `"alloy.device.v2.1"` and whose body satisfies the bundled JSON-
  schema
- **WHEN** alloy-codegen calls `parse_device(text)`
- **THEN** the call SHALL return a `CanonicalDevice` instance
- **AND** every required IR field SHALL be populated (no `None`
  fallbacks on required fields)

### Requirement: The canonical IR SHALL be modelled by `alloy_codegen.ir.v2_1`

The `alloy_codegen.ir.v2_1` package SHALL declare frozen, slotted
dataclasses for every section of the v2.1 schema (`Identity`, `Core`,
`Multicore`, `MemoryRegion`, `Oscillator`, `PLLConfig`, `ClockDomain`,
`ClockProfile`, `SelectRegister`, `Template`, `TemplateRegister`,
`TemplateField`, `PeripheralInstance`, `AdcCalibration`,
`ExternalTrigger`, `I2cTimingPreset`, `Pin`, `PinConstraint`,
`VectorTable`, `InterruptMatrix`).  The legacy
`alloy_codegen.ir.model` module SHALL be removed in the cutover
commit.

#### Scenario: The legacy IR module SHALL be absent post-cutover

- **GIVEN** the cutover commit has landed
- **WHEN** any module attempts `from alloy_codegen.ir.model import …`
- **THEN** the import SHALL raise `ModuleNotFoundError`

### Requirement: The on-disk YAML SHALL NOT carry alloy-codegen-synthesised rows

The v2.1 canonical YAML SHALL omit every row that alloy-codegen
synthesises during normalize: `route_operations`,
`route_requirements`, `connection_candidates`, `connection_groups`,
`interrupt_bindings`, `vector_slots`, `startup_descriptors`,
`signal_endpoints`, `capabilities`, `dma_routes`, `dma_bindings`, and
`ip_blocks`.  These rows SHALL exist only in the in-memory
`SynthesisedDevice` aggregate produced by
`connector_model.build_synthesised(device)`.

#### Scenario: Re-emitted YAML omits all synthesised sections

- **GIVEN** a `CanonicalDevice` instance loaded from a v2.1 YAML
- **WHEN** `serialize_device(device)` is called
- **THEN** the output SHALL NOT contain any of the synthesised
  section keys above
- **AND** the YAML SHALL load back via `parse_device` to a `CanonicalDevice`
  byte-equal under `serialize_device`

### Requirement: Per-row provenance SHALL NOT appear; only top-level provenance is emitted

The v2.1 YAML SHALL carry exactly one `provenance:` block, at the top
level, declaring `primary` (string), `secondary[]` (list of strings),
`authored` (`hand` | `auto` | `auto+hand`), and `authored_on`
(ISO-8601 date string).  Per-row `provenance` blocks on individual
peripherals, registers, fields, etc. SHALL NOT be emitted.

#### Scenario: Round-trip preserves top-level provenance unchanged

- **GIVEN** a v2.1 YAML with `provenance.primary = "cmsis-svd:STM32F103"`
- **WHEN** the file is parsed and re-serialised
- **THEN** the output's `provenance` block SHALL equal the input's
  byte-for-byte

#### Scenario: Per-row provenance triggers a schema rejection

- **GIVEN** a YAML containing `peripherals[0].provenance: { … }`
- **WHEN** alloy-codegen calls `validate_device(text)`
- **THEN** the validator SHALL reject the file
  (per-row provenance is not allowed by the bundled schema)

### Requirement: Templates SHALL define IP register layouts once per IP version

A v2.1 YAML SHALL define each peripheral IP-block layout exactly once
under `templates.<ip>:` and SHALL reference it from each instance via
`peripherals[].template: <ip>` and (optionally) `peripherals[].ip_version`.
Per-instance `registers` / `register_fields` blocks SHALL NOT exist.

#### Scenario: Three USART instances share one template

- **GIVEN** an STM32F103 v2.1 YAML with `templates.usart.fields.cr1.ue: { bit: 13 }`
  and three peripheral instances (`usart1`, `usart2`, `usart3`) all
  declaring `template: usart`
- **WHEN** codegen iterates the device's peripheral instances
- **THEN** all three SHALL resolve `cr1.ue` to bit 13 by template
  lookup
- **AND** the YAML file SHALL NOT carry the `cr1.ue` row three times

### Requirement: Schema validation SHALL run as a hard gate at emission time

The writer SHALL invoke the bundled JSON-schema validator
(`Draft202012Validator`) on the primitive payload before any
`yaml.dump` call.  This applies to
`alloy_data_extractor.emit.canonical_yaml_v2_1.write_device_yaml` and
every direct caller of the writer.  Failures SHALL raise
`StageExecutionError` with a multi-line diagnosis listing every
offending path.  No file SHALL be written when validation fails.

#### Scenario: Drift caught at write time

- **GIVEN** an extractor that produces a payload with
  `pinout[0].constraints: ["magic-pin"]` (not in the schema enum)
- **WHEN** `write_device_yaml(payload, …)` runs
- **THEN** no file SHALL be written
- **AND** a `StageExecutionError` SHALL surface the path
  `pinout/0/constraints/0` and the closed-enum mismatch

### Requirement: The data repository CI SHALL run schema validation on every PR

`alloy-devices-yml` SHALL ship a CI workflow `validate-v21` that runs
the schema validator against every `vendors/**/devices/*.yml` touched
by a PR (or the whole tree on main).  The workflow SHALL fail when
any file fails validation.

#### Scenario: PR introducing a v2.0 file is rejected

- **GIVEN** a PR that adds `vendors/foo/bar/devices/baz.yml` with
  `schema: alloy.device.v2.0`
- **WHEN** the `validate-v21` workflow runs
- **THEN** the workflow SHALL fail
- **AND** the failing job's logs SHALL contain the schema-const
  mismatch message from the validator

### Requirement: The binary IR cache key SHALL incorporate the v2.1 schema constant

Every binary IR cache filename SHALL embed `CANONICAL_SCHEMA = "alloy.device.v2.1"` so a future schema bump invalidates every cached entry implicitly.  The legacy `IR_SCHEMA_VERSION = "1.x.y"` substring SHALL NOT appear in any cache filename produced by `alloy_codegen.sources.alloy_devices_yml` post-cutover.

#### Scenario: Cache writes use the new schema constant

- **GIVEN** a v2.1 YAML loaded for the first time
- **WHEN** the loader writes the IR pickle to disk
- **THEN** the filename SHALL match the pattern
  `<chip>.alloy_device_v2_1.<sha8>.pkl`
- **AND** the pre-cutover pattern `<chip>.1_5_0.<sha8>.pkl`
  SHALL NOT appear

### Requirement: alloy-codegen SHALL deterministically synthesise route_operations from the v2.1 IR

`connector_model.build_synthesised(device)` SHALL produce a
`SynthesisedDevice` whose `route_operations` field, for any v2.1
`CanonicalDevice`, is byte-deterministic across repeated calls and
preserves the typed contract previously enforced in v1
(`target_ref_kind`, `target_ref_id`, `register_id`, `register_field_id`
all populated).

#### Scenario: Two builds produce identical synthesised rows

- **GIVEN** any admitted v2.1 chip
- **WHEN** `connector_model.build_synthesised(device)` is invoked
  twice in the same process
- **THEN** the resulting `route_operations` tuples SHALL be deeply
  equal between the two calls
- **AND** every row SHALL satisfy the typed-ref contract
  (`target_ref_kind` non-None, `target_ref_id` non-None,
  `register_id` non-None, `register_field_id` non-None)

## REMOVED Requirements

### Requirement: ~~Canonical YAML SHALL declare schema_version as semver~~

This requirement is superseded.  v1's free-form `schema_version: "1.x.y"`
field is replaced by the const-locked `schema: "alloy.device.v2.1"`.

### Requirement: ~~Per-row provenance dedup via `provenance_defaults` map~~

Superseded.  v2.1 has no per-row provenance to dedup; the dominant
top-level block is the only block.  The `_compact_provenance_defaults`
/ `_expand_provenance_defaults` helpers are deleted.

### Requirement: ~~The on-disk YAML SHALL carry alloy-codegen synthesised rows when populated~~

Superseded.  Synthesised rows move to in-memory IR only.
