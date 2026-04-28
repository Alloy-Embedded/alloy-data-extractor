# Tasks — migrate-modm-enrichment-extractor

- [ ] 1.1 Port `modm_devices.py` into
      `extractors/modm_devices.py` as a secondary
      `EnrichmentExtractor` (no canonical-YAML output of its
      own; produces an `EnrichmentRecord`).
- [ ] 1.2 Wire the STM32 extractor (Phase 1.1 dependency) to
      call modm enrichment as transitional plumbing until
      Phase 2.2 ships.
- [ ] 1.3 STM32 YAML parity remains byte-identical to today.
- [ ] 1.4 Delete `alloy_codegen/sources/modm_devices.py` and
      any residual imports.
- [ ] 1.5 `openspec validate migrate-modm-enrichment-extractor --strict`.
- [ ] 1.6 Archive + commit in both repos.
