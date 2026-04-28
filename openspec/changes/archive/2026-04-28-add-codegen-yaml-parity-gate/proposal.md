# Add Codegen-Side YAML/Legacy-Path Parity Gate

## Why

The 17 admitted devices already have YAML in alloy-devices-yml,
but alloy-codegen still builds their canonical IR through the
legacy `_build_*_device_ir` callable in `stages/normalize.py`.
The YAML path exists but is not load-bearing — flipping it on
silently could regress IR shape and nobody would notice until
a downstream artifact diff.

Before any vendor migrates from alloy-codegen `sources/` into
the extractor, we need a **byte-identical proof**: for each
admitted device, the IR produced by loading the YAML must equal
the IR produced by the legacy path.  This gate is what makes
"delete the legacy parser" safe, vendor-by-vendor.

## What Changes

- Add `tests/test_yaml_parity_gate.py` to alloy-codegen.
  Parametrised over every admitted device:
  1. Build IR via the legacy path (`_build_<vendor>_device_ir`).
  2. Build IR via the YAML path (`alloy_devices_yml.load_canonical_device(...)`).
  3. Assert the two `CanonicalDeviceIR` instances are byte-equal
     (compare via deterministic `repr()` or a structural diff helper).
- Test failures emit a per-field diff so reviewers can see
  exactly which IR surface drifted.
- A `--write-fixtures` flag regenerates the YAML from the legacy
  path (gated behind a CLI flag, never auto-run in CI) — this is
  how a maintainer fixes drift after a deliberate IR change.
- The gate runs in alloy-codegen's regular pytest suite; failure
  is a hard CI red.

## Impact

- Affected: alloy-codegen test suite + `alloy_devices_yml.py`
  loader (must be exercised by 17 devices, not just the 4 it
  may currently cover).
- Detects any YAML/legacy drift before a Phase-1 migration
  would silently break a vendor.
- Pre-condition for `migrate-stm32-extractor` (1.1) and every
  subsequent migration: parity green for that vendor's devices.

## What this does NOT do

- Does not migrate any vendor parser.
- Does not change YAML or IR shape.
- Does not enforce parity for non-admitted devices (those don't
  have YAMLs yet, by definition).
