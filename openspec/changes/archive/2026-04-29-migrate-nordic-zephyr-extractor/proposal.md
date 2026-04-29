# Migrate Nordic Zephyr-DTS Extraction into alloy-data-extractor

## Why

Today there are **two** Zephyr-DTS adapters:
`alloy-codegen/src/alloy_codegen/sources/zephyr_dts.py` (604 LOC,
the in-tree origin) and
`alloy-data-extractor/src/.../extractors/zephyr_dts.py` (518 LOC,
the migrated copy).  Plus `zephyr_pinctrl.py` (281 LOC) on the
codegen side which decodes pinctrl groups into connection
candidates.  This duplication invites drift — every fix lands
in two places.

This change consolidates: the alloy-data-extractor copy becomes
the single source of truth, the codegen copy is deleted, and
the pinctrl decoder ports over.  Nordic nRF52 is the one
admitted device today.

## What Changes

- `alloy-data-extractor/src/.../extractors/zephyr_dts.py` is
  promoted to the canonical Zephyr-DTS extractor.
- Pinctrl decoder ported from
  `alloy-codegen/src/alloy_codegen/sources/zephyr_pinctrl.py`
  into `alloy-data-extractor/src/.../extractors/zephyr_dts/pinctrl.py`.
- The extractor module split into a package:
  `extractors/zephyr_dts/{__init__.py,maps.py,parser.py,pinctrl.py}`.
- alloy-codegen: delete `sources/zephyr_dts.py` (604 LOC) +
  `sources/zephyr_pinctrl.py` (281 LOC).  Delete
  `_build_zephyr_dts_device_ir` from `stages/normalize.py`.
- nRF52 device admitted via canonical YAML only.

## Impact

- alloy-data-extractor: +281 LOC (pinctrl) and modest
  refactor of existing 518 LOC.
- alloy-codegen: -885 LOC (zephyr_dts + zephyr_pinctrl) plus
  one normalize entry point.
- alloy-devices-yml: nrf52840.yml rewritten byte-identical.
- Vocabulary maps for the 8 Zephyr-supported vendors (added
  in alloy-codegen by `extend-zephyr-dts-vendor-coverage`)
  are already present in the extractor copy.

## What this does NOT do

- Does not admit any non-Nordic Zephyr device.  Vocabulary is
  ready; admissions land later via
  `add-bulk-discovery-cmsis-pack-manager`.
- Does not change the IR shape.
