# Tasks — add-stm32-cubemx-db-extractor

## Scaffold (autonomous round)

- [x] S.1 Register `stm32-cubemx` extractor with synthetic
      family binding (it's a secondary EnrichmentExtractor —
      not picked by resolver, only via merge engine + explicit id).
- [x] S.2 STM32_MERGE_POLICY (Phase 2.2) already declares CubeMX
      as authority for `pins`, `clock_nodes`, `dma_requests`.
- [x] S.3 Test scaffold registration + secondary-binding behaviour.

## Phase 1: Parser port

- [ ] 1.1 Implement `extractors/stm32_cubemx.py` parsing
      `db/mcu/*.xml`.
- [ ] 1.2 Pin entry `stm32cubemx-db` in `data/source_pins.toml`.
- [ ] 1.3 Re-emit STM32 YAMLs; document parity-gate
      regeneration (this is an enrichment, not byte-identical).
- [ ] 1.4 Test on representative STM32 chip across 3 series
      (F0, F4, G0).
- [ ] 1.5 `openspec validate add-stm32-cubemx-db-extractor --strict`.
- [ ] 1.6 Archive + commit.
