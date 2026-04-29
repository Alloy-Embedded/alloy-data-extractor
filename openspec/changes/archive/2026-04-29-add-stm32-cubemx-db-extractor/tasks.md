# Tasks — add-stm32-cubemx-db-extractor

## Scaffold (autonomous round)

- [x] S.1 Register `stm32-cubemx` extractor with synthetic
      family binding (it's a secondary EnrichmentExtractor —
      not picked by resolver, only via merge engine + explicit id).
- [x] S.2 STM32_MERGE_POLICY (Phase 2.2) already declares CubeMX
      as authority for `pins`, `clock_nodes`, `dma_requests`.
- [x] S.3 Test scaffold registration + secondary-binding behaviour.

## Phase 1: Parser port

- [x] 1.1 Implement `extractors/stm32_cubemx.py` parsing
      `db/mcu/*.xml` — MCU root + GPIO IP AF table + DMA IP
      request matrix + `db/plugins/clock/*.xml` clock-tree edges.
- [x] 1.2 Pin entry `stm32cubemx-db` in `data/source_pins.toml`
      (CubeMX v6.17, ST proprietary — never bundled).
- [ ] 1.3 Re-emit STM32 YAMLs; document parity-gate
      regeneration (this is an enrichment, not byte-identical).
      *Deferred to a daytime session: needs a bulk-mode pass
      against the local CubeMX install and a parity-gate
      regeneration in alloy-codegen.*
- [x] 1.4 Test on representative STM32 chip across 3 series
      (F0 = stm32f071rb, F4 = stm32f407vg, G0 = stm32g071rb) —
      synthetic-fixture suite + opt-in real-DB smoke tests
      against `/Applications/STMicroelectronics/STM32CubeMX.app`.
- [x] 1.5 `openspec validate add-stm32-cubemx-db-extractor --strict`.
- [ ] 1.6 Archive + commit — kept open until Phase 1.3 lands
      bulk re-emission and the parity-gate regeneration.
