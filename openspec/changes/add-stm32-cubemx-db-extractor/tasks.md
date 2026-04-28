# Tasks — add-stm32-cubemx-db-extractor

- [ ] 1.1 Implement `extractors/stm32_cubemx.py` parsing
      `db/mcu/*.xml`.
- [ ] 1.2 Register as secondary `EnrichmentExtractor`.
- [ ] 1.3 Define `MergePolicy.STM32` declaring CubeMX as authority
      for pinmux + clock-tree + DMA request matrix.
- [ ] 1.4 Pin entry `stm32cubemx-db` in `data/source_pins.toml`.
- [ ] 1.5 Re-emit STM32 YAMLs; document parity-gate
      regeneration (this is an enrichment, not byte-identical).
- [ ] 1.6 Test on representative STM32 chip across 3 series
      (F0, F4, G0).
- [ ] 1.7 `openspec validate add-stm32-cubemx-db-extractor --strict`.
- [ ] 1.8 Archive + commit.
