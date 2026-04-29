# Tasks — migrate-modm-enrichment-extractor

## Phase 1: Parser port (autonomous round)

- [x] 1.1 Port `modm_devices.py` into
      `extractors/modm_devices.py` as a secondary
      EnrichmentExtractor.  Parses RCC clock-tree edges, DMA
      request matrix, and per-pin alternate-function tuples
      from modm-devices XML.
- [x] 1.2 Project parsed tuples into a canonical-IR-shaped
      payload (`clock_nodes`, `clock_selectors`, `dma_bindings`,
      `pins`) that the merge engine (Phase 2.2) consumes.
- [x] 1.3 Register via `@register_extractor("modm-devices",
      families=(("__modm_secondary__", "__modm_secondary__"),))`
      so the resolver picks STM32-primary stm32 and modm is
      invoked explicitly via the merge engine.

## Phase 2: Tests + merge integration

- [x] 2.1 Synthetic-XML unit tests covering RCC / DMA / GPIO
      driver parsing.
- [x] 2.2 End-to-end test: stm32 primary + modm enrichment +
      merge_payloads → field_provenance correctly attributes
      clock_nodes / dma_bindings to modm-devices.
- [x] 2.3 STM32_MERGE_POLICY (Phase 2.2) declares modm-devices
      as authority for `clock_nodes`, `clock_selectors`,
      `dma_bindings` — verified by the e2e test.

## Phase 3: Codegen-side cleanup (deferred to a daytime session)

- [ ] 3.1 Verify the codegen parity gate stays green for STM32
      after re-emitting YAMLs through `extractor → merge →
      write_device_yaml`.
- [ ] 3.2 Delete `alloy_codegen/sources/modm_devices.py`.
- [ ] 3.3 Strip the `apply_modm_enrichment` call from the
      codegen normalize stage.
- [ ] 3.4 Remove modm-related entries from `_KNOWN_DRIFT` (no
      ST devices currently in there).

## Phase 4: Validate + archive

- [x] 4.1 `openspec validate migrate-modm-enrichment-extractor --strict`.
- [x] 4.2 Pytest green (139/139 + 1 skip across the extractor suite).
- [ ] 4.3 Archive — kept open until Phase 3 codegen-side
      deletion lands.
