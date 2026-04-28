# Tasks — define-extractor-protocol

## Phase 1: Protocol module

- [ ] 1.1 Create `src/alloy_data_extractor/extractor_protocol.py`.
- [ ] 1.2 Define `ExtractionRequest`, `ExtractionResult`,
      `ProvenanceRecord` dataclasses.  Frozen, slotted.
- [ ] 1.3 Define `Extractor(Protocol)` with the
      `extract(request) -> ExtractionResult` method.
- [ ] 1.4 Add `register_extractor(extractor_id, vendors,
      families)` decorator that fills a module-level registry.
- [ ] 1.5 Add `resolve_extractor(vendor, family)` plus an
      explicit `resolve_extractor_by_id(extractor_id)`.

## Phase 2: Refactor existing extractors

- [ ] 2.1 Refactor `cmsis_svd.py` to expose an `Extractor`
      instance registered for the vendors it covers.
- [ ] 2.2 Refactor `zephyr_dts.py` to do the same.
- [ ] 2.3 Both extractors keep their public helpers
      (`parse_zephyr_device_document`, etc.) for tests.

## Phase 3: Pipeline dispatch

- [ ] 3.1 Replace `_EXTRACTORS = {...}` with a generic
      `resolve_extractor(vendor, family)` lookup.
- [ ] 3.2 CLI: `--extractor` flag becomes optional; auto-resolve
      when only one extractor admits the (vendor, family) pair.
- [ ] 3.3 CLI: `--source <key>=<value>` carries arbitrary keys
      that flow into `ExtractionRequest.source_paths`.

## Phase 4: Tests

- [ ] 4.1 Test the registry rejects duplicate extractor_ids.
- [ ] 4.2 Test `resolve_extractor` raises a clear error when no
      extractor admits a `(vendor, family)` pair.
- [ ] 4.3 Test that the refactored cmsis-svd extractor produces
      byte-identical YAML to the pre-refactor version on the
      bundled fixture (regression guard).

## Phase 5: Validate + archive

- [ ] 5.1 `openspec validate define-extractor-protocol --strict`
- [ ] 5.2 Full pytest pass.
- [ ] 5.3 Archive + commit.
