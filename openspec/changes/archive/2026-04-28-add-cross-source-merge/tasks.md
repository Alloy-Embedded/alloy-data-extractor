# Tasks — add-cross-source-merge

- [x] 1.1 Define `MergePolicy` dataclass + `merge_payloads(...)`
      in `alloy_data_extractor.merge`.
- [x] 1.2 Per-field provenance annotation survives YAML
      serialisation.
- [x] 1.3 Schema bumps to `1.3.0`; add optional
      `provenance.field_provenance` (inverted index).
- [x] 1.4 STM32 extractor consumes modm enrichment via merge
      (replaces transitional plumbing from
      `migrate-modm-enrichment-extractor`).
- [x] 1.5 Re-emit all 17 admitted YAMLs at v1.3.0; parity gate
      stays green.
- [x] 1.6 `openspec validate add-cross-source-merge --strict`.
- [x] 1.7 Archive + commit.
