# Add STM32CubeMX MCU Database Extractor

## Why

CMSIS-SVD covers STM32 register layouts but is silent on:
- Pinmux alternate-function tables (which AF maps which signal
  to which pin)
- Clock-tree edges (which mux routes which oscillator)
- DMA request matrix (which peripheral signal maps to which DMA
  request id)

These facts live in the **STM32CubeMX MCU Database** — XML files
shipped inside ST's CubeMX installation under `db/mcu/`.  This
is the only authoritative pinmux + clock-tree source for the
full STM32 catalog (~1,500 chips).

## What Changes

- New extractor `alloy_data_extractor.extractors.stm32_cubemx`
  that reads `db/mcu/*.xml` files.
- Registers as a **secondary** `EnrichmentExtractor` (per
  `add-cross-source-merge`) — it composes with the primary STM32
  CMSIS-SVD extractor rather than producing standalone YAMLs.
- `MergePolicy.STM32` declares CubeMX as the source of truth
  for `pins[*].alternate_functions`, `clock_nodes`, and
  `dma_requests`.
- Pin manifest gains a new entry: `stm32cubemx-db` with a
  pinned CubeMX version (e.g. `v6.10.0`).
- License note: CubeMX DB is redistributable under specific
  terms; extractor SHALL refuse to bundle the DB itself,
  consuming a user-provided checkout instead.

## Impact

- alloy-data-extractor: +~600 LOC.
- alloy-devices-yml: existing STM32 YAMLs gain richer
  `pins[*].alternate_functions` + `clock_nodes` surface
  (parity gate must be regenerated for STM32 — this is a
  documented IR enrichment, not byte-identical).
- Bulk discovery (Phase 2.1) for ST gains pinmux + clock data
  for ~1,500 STM32 chips.

## What this does NOT do

- Does not bundle CubeMX itself — user supplies the path.
- Does not extend pinmux to non-ST vendors.  Pinctrl for
  Renesas / TI / etc. lives in their respective DTS / SDK
  sources.
