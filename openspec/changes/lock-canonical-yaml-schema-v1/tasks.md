# Tasks — lock-canonical-yaml-schema-v1

## Phase 1: Versioning contract

- [ ] 1.1 Document the `schema_version` semver rule in
      `alloy-devices-yml/schema/README.md`.
- [ ] 1.2 Pin the current schema as `1.2.0` in `device.schema.json`
      `$id` URI.
- [ ] 1.3 Decide which YAML fields are REQUIRED at v1 (today only
      `schema_version` and `identity` are; consider promoting
      `provenance` and `memories`).

## Phase 2: Extractor enforcement

- [ ] 2.1 Add `validate_yaml_file(path: Path) -> tuple[ValidationError, ...]`
      in `alloy_data_extractor.emit.canonical_yaml`.
- [ ] 2.2 Make `write_device_yaml(...)` raise when the payload's
      `schema_version` is missing or mismatches the bundled schema.
- [ ] 2.3 Test: synthetic payload with no `schema_version` →
      writer raises a structured error.

## Phase 3: Codegen consumer rejection

- [ ] 3.1 In alloy-codegen `sources/alloy_devices_yml.py`, reject
      YAMLs whose `schema_version` major ≠ codegen's pinned major.
- [ ] 3.2 Pinned major lives in `alloy_codegen.bootstrap.IR_SCHEMA_MAJOR`.
- [ ] 3.3 Test: synthetic YAML with `schema_version: 2.0.0` →
      codegen raises `IRSchemaVersionMismatch`.

## Phase 4: alloy-devices-yml CI gate

- [ ] 4.1 Add `tools/validate_all_yamls.py` that walks
      `vendors/**/devices/*.yml` and validates each.
- [ ] 4.2 Wire it into the alloy-devices-yml GitHub Actions workflow
      as a required check.
- [ ] 4.3 Document in `CONTRIBUTING.md` how to run validation
      locally before pushing.

## Phase 5: Validate + archive

- [ ] 5.1 `openspec validate lock-canonical-yaml-schema-v1 --strict`
- [ ] 5.2 Re-run all alloy-devices-yml YAMLs through the validator.
- [ ] 5.3 Archive + commit.
