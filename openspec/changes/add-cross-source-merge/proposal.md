# Add Cross-Source Merge

## Why

A single chip is often described by **multiple** authoritative
sources, each better at some facets:

- **CMSIS-SVD**: register layout + IRQ table.  Weak on pinmux,
  almost no clock-tree edges.
- **STM32CubeMX DB**: pinmux + clock tree + DMA request matrix.
  Lives only for STM32.
- **modm-devices**: enriched DMA + AF tables for STM32 and SAM.
- **Zephyr DTS**: cross-vendor pinmux + interrupts + memory
  regions, but no register layout.
- **Vendor SDK headers**: clock-gate bits + low-level peripheral
  facts that other sources miss.

The extractor today picks one source per chip.  A real STM32
chip wants `CMSIS-SVD ⊕ STM32CubeMX ⊕ modm-devices` — merged
deterministically, with each field carrying provenance for
which source supplied it.

## What Changes

- New module `alloy_data_extractor.merge` with:
  - `MergePolicy` — declares per-field source priority.  E.g.
    `peripherals.base_address` takes CMSIS-SVD; `peripherals.dma_bindings`
    takes modm if present, else CubeMX, else nothing.
  - `merge_payloads(primary, *enrichments, policy)` — folds an
    `EnrichmentRecord` (from `migrate-modm-enrichment-extractor`)
    onto a primary payload.
  - Per-field provenance: every merged field SHALL carry a
    `_provenance: {source_id, revision}` annotation that
    survives YAML serialisation.
- The extractor pipeline becomes: discover → primary extract →
  list secondary enrichments → merge → schema-validate → write.
- New schema field: `provenance.field_provenance` (an inverted
  index: source_id → list of paths the source supplied).

## Impact

- alloy-data-extractor: ~600-900 LOC for merge engine + policies.
- alloy-devices-yml: schema bumps to `1.3.0` (new optional
  `provenance.field_provenance`).
- All existing YAMLs SHALL be re-emitted at v1.3.0 (parity gate
  catches any IR drift; field_provenance is additive).

## What this does NOT do

- Does not auto-discover which sources to merge.  The
  `MergePolicy` is human-curated per family.
- Does not implement new sources (CubeMX is `add-stm32-cubemx-db-extractor`).
