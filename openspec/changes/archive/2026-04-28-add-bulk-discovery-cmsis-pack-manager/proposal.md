# Add Bulk Discovery via CMSIS-Pack Manager

## Why

After Phase 1, every admitted vendor has an extractor in
alloy-data-extractor.  But admitting a *new* device still
requires a human to discover its name, find its CMSIS-Pack /
ATDF / SDK header, and pin the source manually.  This does not
scale to 5,000 ARM chips.

`cmsis-pack-manager` (already declared in `pyproject.toml`)
gives programmatic access to the CMSIS-Pack catalog.  This
change adds a `bulk` subcommand that discovers every chip in a
vendor's pack catalog and fans them out to the right extractor.

## What Changes

- New CLI subcommand: `alloy-data-extract bulk --vendor st`.
  Walks the cmsis-pack-manager catalog, discovers every device
  in the vendor's packs, dispatches each through the registered
  extractor, writes one YAML per device to alloy-devices-yml.
- Discovery output is deterministic: same pack revision →
  same set of chips, same order.
- Per-chip failure (missing source file, unsupported family,
  schema-validation error) does not halt the run; failures are
  collected into a `bulk-report.json` listing each chip with its
  status (`PASS`, `EXTRACT_FAILED`, `SCHEMA_INVALID`,
  `NO_EXTRACTOR_REGISTERED`).
- A `--dry-run` flag lists what would be extracted without
  writing files.
- A `--filter <regex>` flag scopes the run.
- Sharded mode: `--shard 1/8` for CI parallelism.

## Impact

- alloy-data-extractor: ~400-600 LOC for discovery + dispatch +
  reporting.
- alloy-devices-yml: gains potentially thousands of new YAMLs
  in one PR (gated by review process — typically split per
  vendor).
- CI runtime: full bulk run for ST alone (~300 chips) targets
  under 10 minutes single-threaded.

## What this does NOT do

- Does not implement cross-source merge (Phase 2.2).  Bulk
  discovery uses one source per chip — the primary extractor
  registered for that chip's family.
- Does not gate alloy-codegen.  Bulk-discovered chips are
  *available* via YAML; codegen admits them only when their
  family's emitter pipeline supports them.
