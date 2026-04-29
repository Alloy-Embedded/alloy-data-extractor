# SUPERSEDED — archived without per-task completion

## Why this archive carries unchecked tasks

This change was authored before the architectural pivot recorded
in alloy-codegen's `consume-alloy-devices-yml-as-canonical-input`
(archived 2026-04-29).  It described a vendor-by-vendor migration
recipe whose core invariants no longer apply:

1. **The codegen-side parity gate is no-op.**  The legacy
   `_build_<vendor>_device_ir` paths the gate compared against
   were *deleted wholesale* by the consume-alloy-devices-yml
   refactor, not vendor-by-vendor as this change planned.
   `tests/test_yaml_parity_gate.py` skips 17/17 today because
   `resolve_vendor_adapter` has nothing to resolve.

2. **The codegen-side `sources/<vendor>.py` modules are gone.**
   `alloy-codegen/src/alloy_codegen/sources/` now contains only
   `alloy_devices_yml.py`.  There is no per-vendor parser to
   delete; the deletion in this change's tasks 3.x / 5.x is
   simply not applicable.

3. **The "primary surface" of the migration was completed
   autonomously** during the multi-session push that closed
   Phase 0 + Phase 2 + Phase 3-4 (see `PHASE_1_HANDOFF.md`).
   Each `extractors/<vendor>.py` module exists in
   alloy-data-extractor and is exercised by its own test suite.

## What "remaining" tasks would have been

The unchecked tasks describe:

- Re-extracting the admitted devices and overwriting their
  YAMLs in alloy-devices-yml.
- Verifying the parity gate stays green.
- Deleting codegen-side parsers + `_build_<vendor>_device_ir`
  helpers.

Items 2 and 3 are moot (no parity-gate target, nothing to
delete).  Item 1 is partially blocked: as documented during the
2026-04-29 work session, fresh re-emission of STM32 chips
through the merge engine still produces YAMLs that lack
CubeMX-derivable `ip_name`/`ip_version`/`instance` fields plus
`bootstrap-patch` overrides — overwriting today would regress
those YAMLs.  Closing that gap is tracked separately as a
follow-up to the cmsis-svd register-tree + per-row provenance
work that landed under commits 18fd166 + 7fb4dc3.

## Where to look next

- `extractors/<vendor>.py` for the migrated parser surface.
- `merge.py` + `STM32_MERGE_POLICY` for cross-source composition.
- Commits 9d95488 / 18fd166 / 7fb4dc3 for the ongoing
  enrichment of the primary STM32 path.
- alloy-codegen's consume-alloy-devices-yml-as-canonical-input
  archive for the deletion side of the story.
