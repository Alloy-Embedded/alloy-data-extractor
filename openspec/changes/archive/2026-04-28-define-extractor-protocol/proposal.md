# Define the Extractor Protocol

## Why

Today `alloy_data_extractor.pipeline._EXTRACTORS` is a dict
mapping a string id to a module.  The pipeline calls
`extractor.extract_device(vendor=..., family=..., device=...,
svd_path=..., revision=...)` and assumes the return shape
matches what `cmsis_svd.py` produces.  This is fragile:

- The `svd_path` parameter is CMSIS-SVD-specific.  Zephyr DTS
  passes `dts_path`; ATDF will pass `atdf_path`; PIC packs pass
  `dfp_path`.  The pipeline already special-cases this.
- Each extractor invents its own return type
  (`CmsisSvdExtraction`, `ZephyrExtraction`, ...).
- Adding a new extractor requires editing the pipeline, not
  just adding a module.

Before the 7 Phase-1 migrations land, freeze a single
`Extractor` protocol so each migration can plug in without
touching the pipeline.

## What Changes

- New module `alloy_data_extractor.extractor_protocol` defines:
  - `class Extractor(Protocol)` — `extract(request: ExtractionRequest) -> ExtractionResult`.
  - `@dataclass ExtractionRequest` — uniform input: `vendor`, `family`, `device`, `source_paths: dict[str, Path]`, `revision`, `extra: dict[str, Any]`.
  - `@dataclass ExtractionResult` — uniform output: `payload: dict`, `provenance: ProvenanceRecord`, `warnings: tuple[str, ...]`.
  - `@dataclass ProvenanceRecord` — `source_id`, `source_path`, `revision`, `extracted_at`, `patch_ids`.
- `Extractor` instances register themselves via `@register_extractor("<id>", supports=("vendor", "family"))`.
- The pipeline dispatches generically through `resolve_extractor(vendor, family) -> Extractor`.
- Existing `cmsis_svd` and `zephyr_dts` extractors are refactored to fit the protocol; behaviour byte-identical.

## Impact

- Affected: pipeline dispatcher, both existing extractors, CLI argument parsing.
- All 4 currently-extracted devices (whatever was demo'd) continue to produce byte-identical YAML.
- Phase 1 migrations now have a clean target to implement against.

## What this does NOT do

- Does not migrate any new vendor parser yet.
- Does not change the YAML schema — output bytes are unchanged.
