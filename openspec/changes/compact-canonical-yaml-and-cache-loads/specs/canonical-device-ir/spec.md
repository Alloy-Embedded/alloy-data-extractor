# Spec — Canonical Device IR (compact + cache delta)

## ADDED Requirements

### Requirement: The canonical YAML SHALL omit pure-diagnostic fields the codegen never reads

The canonical YAML serializer SHALL NOT emit the following
dataclass fields when their value is the default empty / null:

- `RouteOperation.target`, `RouteOperation.value`,
  `RouteOperation.subject_kind`, `RouteOperation.subject_id`,
  `RouteOperation.register_peripheral`,
  `RouteOperation.register_name`,
  `RouteOperation.register_offset`.
- `RouteRequirement.target`, `RouteRequirement.value`.
- `ClockGateDescriptor.register_peripheral`,
  `ClockGateDescriptor.register_name`,
  `ClockGateDescriptor.register_offset`.
- `ResetDescriptor.register_peripheral`,
  `ResetDescriptor.register_name`,
  `ResetDescriptor.register_offset`.
- `VectorSlotDescriptor.core_affinity` when equal to `"cpu0"`.

Each affected dataclass field SHALL declare an
`omit_if_empty` (or `omit_if_default` for `core_affinity`)
metadata flag on the field.  All extractors in
`alloy_data_extractor` SHALL stop populating these fields
explicitly; payloads that historically carried values SHALL
continue to round-trip through `parse_device(text)` because
the IR keeps each field optional with a default.

#### Scenario: parse_device tolerates missing diagnostic fields

- **GIVEN** a canonical YAML payload that omits every field
  listed above
- **WHEN** alloy-codegen calls
  `parse_device(text)`
- **THEN** the returned `CanonicalDeviceIR` SHALL be valid
- **AND** every `RouteOperation` row SHALL have
  `target = None`, `value = None`,
  `register_peripheral = None`, `register_name = None`,
  `register_offset = None`
- **AND** validation SHALL succeed without diagnostics
  (validation only checks `register_id` / `register_field_id`
  presence)

#### Scenario: serialize_device round-trip is byte-stable on stripped payload

- **GIVEN** a `CanonicalDeviceIR` instance with the seven
  diagnostic fields unset
- **WHEN** `serialize_device(ir)` is called twice
- **THEN** the two outputs SHALL be byte-identical
- **AND** neither output SHALL contain any of the dropped
  field names as a YAML key

### Requirement: Per-row provenance SHALL move to a sibling audit sidecar at schema 1.5.0

A schema 1.5.0 canonical YAML SHALL NOT emit per-row
`provenance` blocks.  An accompanying audit sidecar at
`<vendor>/<family>/devices/<device>.audit.yml` SHALL carry
the per-row provenance payload as a flat mapping
`{<row_id>: Provenance}` keyed by the dataclass’s primary
identifier (`register_id`, `field_id`, `operation_id`,
`requirement_id`, `gate_id`, `reset_id`, `binding_id`,
`profile_id`, `node_id`, `pin_name`, `pad_id`,
`peripheral_name`, etc.).

The canonical YAML’s top-level `provenance` block SHALL
remain — it carries the device-wide identity and source
bundle.  A new top-level field `provenance_audit_path`
(string, optional) SHALL declare the sidecar path
relative to the canonical YAML.

`parse_device(text, *, audit_text=None)` SHALL accept the
sidecar text and overlay it onto the parsed IR so the
returned `CanonicalDeviceIR` is shape-equivalent to a
schema 1.4.0 parse.  When `audit_text is None` the parser
SHALL synthesise each row’s provenance from the top-level
bundle so existing emitters never crash on a missing
sidecar.

#### Scenario: serialize emits both files in lockstep

- **GIVEN** a `CanonicalDeviceIR` instance
- **WHEN** the data-extractor pipeline calls
  `serialize_device(ir)`
- **THEN** the function SHALL return a dataclass
  `SerializedDevice(canonical_text, audit_text)`
- **AND** writing the canonical YAML without writing the
  sidecar SHALL be detectable by tooling
  (`alloy-data-extractor publish` aborts the publish if
  either file fails to write)

#### Scenario: alloy-devices-yml load round-trips with sidecar

- **GIVEN** a 1.5.0 canonical YAML and its audit sidecar
- **WHEN** `load_canonical_device(...)` reads them
- **THEN** the resulting IR SHALL satisfy
  `to_primitive(ir) == to_primitive(legacy_1_4_0_ir)` for
  every row’s provenance content
- **AND** `runtime_reports.py` SHALL be able to render its
  audit/explainability output unchanged

#### Scenario: codegen accepts 1.5.0 YAML when sidecar is missing

- **GIVEN** a 1.5.0 canonical YAML *without* a sibling
  `<device>.audit.yml`
- **WHEN** alloy-codegen calls `load_canonical_device(...)`
- **THEN** the load SHALL succeed
- **AND** every row’s `provenance.source_id` SHALL equal the
  top-level bundle’s `source_id`
- **AND** `runtime_reports.py` SHALL render
  `audit-sidecar-missing` for each affected row in the
  explainability output instead of crashing

### Requirement: alloy-codegen SHALL cache the parsed IR keyed by YAML SHA

`load_canonical_device` SHALL maintain a binary cache at
`.cache/canonical_ir/<vendor>/<family>/<device>.<sha8>.pkl`
where `sha8 = sha256(canonical_text)[:16]`.  On every call:

1. Hash the canonical YAML text (already read from disk).
2. If the cache file for `(IR_SCHEMA_VERSION, sha8)` exists,
   `pickle.loads` it and return the IR — no YAML parse, no
   `from_primitive` walk.
3. Else parse the YAML normally, write the cache atomically
   via `os.replace`, and return the IR.

The cache key SHALL incorporate `IR_SCHEMA_VERSION` so any
schema bump invalidates every cached entry implicitly.  The
cache directory SHALL be configurable via the
`ALLOY_CODEGEN_IR_CACHE_DIR` env var, and the cache SHALL be
disabled when `ALLOY_CODEGEN_IR_CACHE=0`.

#### Scenario: warm cache returns IR in <100 ms for a 5 MB YAML

- **GIVEN** a freshly-parsed `atsame70q21b.yml` whose IR has
  been cached
- **WHEN** `load_canonical_device(...)` is called a second
  time
- **THEN** the call SHALL return in under 200 ms wall clock
- **AND** the returned IR SHALL be deeply equal to the
  original parse result

#### Scenario: edited YAML invalidates the cache automatically

- **GIVEN** a cached IR whose canonical YAML is then edited
  on disk
- **WHEN** `load_canonical_device(...)` is called
- **THEN** the SHA mismatch SHALL trigger a re-parse
- **AND** the cache file SHALL be replaced atomically with
  the new IR’s pickle

#### Scenario: ALLOY_CODEGEN_IR_CACHE=0 forces re-parse

- **GIVEN** a cached IR
- **WHEN** the env var `ALLOY_CODEGEN_IR_CACHE=0` is set
  before `load_canonical_device(...)` is called
- **THEN** the cache SHALL be ignored
- **AND** a fresh YAML parse SHALL run
- **AND** the cache file on disk SHALL NOT be modified
