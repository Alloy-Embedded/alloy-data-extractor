# Lock Canonical YAML Schema v1

## Why

`alloy-devices-yml/schema/canonical_device/device.schema.json`
already exists and the 17 admitted devices already validate
against it.  But there is no enforcement: extractors don't have
to validate before writing, codegen doesn't refuse non-validated
input, and `schema_version` in the YAMLs is informally `1.2.0`
without anyone owning what "1.2.0" means.

Before any vendor migrates from alloy-codegen into the
extractor, the schema must be a versioned contract: a known
version number, a known set of required fields, and refusal to
load any YAML that violates it on either side.

## What Changes

- Promote `schema_version` to a hard contract: every YAML MUST
  carry a `schema_version` matching the current schema's
  `$id` version (`1.x.x`).  The extractor's
  `canonical_yaml.write_device_yaml(...)` SHALL refuse to write
  a payload missing this field.
- Add `validate_yaml_file(path)` to alloy-data-extractor that
  loads + validates a YAML against the bundled schema, returning
  a structured error list (path, message, severity).
- Add a CI gate in alloy-devices-yml: every committed YAML in
  `vendors/**/devices/*.yml` SHALL validate, or the PR fails.
- Document the version-bump rule:
  - **Patch** (`1.2.0 → 1.2.1`): purely additive new optional
    fields.  Existing YAMLs continue to validate.
  - **Minor** (`1.2.x → 1.3.0`): new required fields with a
    backfill path.  All existing YAMLs SHALL be rewritten.
  - **Major** (`1.x.x → 2.0.0`): incompatible restructuring.
    Codegen + extractor pin to one major.
- Codegen-side: `alloy_codegen.sources.alloy_devices_yml` SHALL
  reject YAMLs whose `schema_version` major ≠ the codegen's
  pinned major.

## Impact

- Affected repos: `alloy-data-extractor` (validator + writer
  refusal), `alloy-codegen` (consumer-side rejection),
  `alloy-devices-yml` (CI gate).
- All 17 existing YAMLs SHALL continue to validate without edits.
- This is the **prerequisite** for every Phase-1 vendor
  migration: without a locked schema, parity guarantees are
  meaningless.

## What this does NOT do

- Does not change the schema's *shape* (fields, types).
  Reshape proposals come separately and bump the version.
- Does not migrate any vendor parser yet.  Pure contract work.
