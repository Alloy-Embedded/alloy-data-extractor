# Tasks — define-extractor-protocol

## Phase 1: Protocol module

- [x] 1.1 Create `src/alloy_data_extractor/extractor_protocol.py`.
- [x] 1.2 Define `ExtractionRequest`, `ExtractionResult`,
      `ProvenanceRecord` dataclasses.  Frozen, slotted.
- [x] 1.3 Define `Extractor(Protocol)` with the
      `extract(request) -> ExtractionResult` method.
- [x] 1.4 Add `register_extractor(extractor_id, vendors,
      families)` decorator that fills a module-level registry.
- [x] 1.5 Add `resolve_extractor(vendor, family)` plus an
      explicit `resolve_extractor_by_id(extractor_id)`.

## Phase 2: Refactor existing extractors

- [x] 2.1 Refactor `cmsis_svd.py` to expose an `Extractor`
      instance registered for the vendors it covers.
- [x] 2.2 Refactor `zephyr_dts.py` to do the same.
- [x] 2.3 Both extractors keep their public helpers
      (`parse_zephyr_device_document`, etc.) for tests.

## Phase 3: Pipeline dispatch

- [x] 3.1 Replace `_EXTRACTORS = {...}` with a generic
      `resolve_extractor(vendor, family)` lookup.
- [x] 3.2 CLI: `--extractor` flag becomes optional; auto-resolve
      when only one extractor admits the (vendor, family) pair.
- [x] 3.3 CLI: `--source <key>=<value>` carries arbitrary keys
      that flow into `ExtractionRequest.source_paths`.

## Phase 4: Tests

- [x] 4.1 Test the registry rejects duplicate extractor_ids.
- [x] 4.2 Test `resolve_extractor` raises a clear error when no
      extractor admits a `(vendor, family)` pair.
- [x] 4.3 Test that the refactored cmsis-svd extractor produces
      byte-identical YAML to the pre-refactor version on the
      bundled fixture (regression guard).

## Phase 5: Validate + archive

- [x] 5.1 `openspec validate define-extractor-protocol --strict`
- [x] 5.2 Full pytest pass.
- [x] 5.3 Archive + commit.
