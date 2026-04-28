# Tasks — migrate-stm32-extractor

## Phase 1: Port the parser

- [ ] 1.1 Copy `alloy-codegen/src/alloy_codegen/sources/stm32_open_pin_data.py`
      → `alloy-data-extractor/src/alloy_data_extractor/extractors/stm32_open_pin_data.py`.
- [ ] 1.2 Port the ST-specific branches of `cmsis_svd.py` into
      a shared helper module.
- [ ] 1.3 Compose them in `extractors/stm32.py` exposing one
      `Extractor` instance registered for `("st", "stm32f4")`
      and `("st", "stm32g0")`.

## Phase 2: Re-extract admitted devices

- [ ] 2.1 Run the extractor against the 5 admitted ST devices.
- [ ] 2.2 Diff each output against the existing YAML in
      alloy-devices-yml.  Drift SHALL be zero.
- [ ] 2.3 Commit any provenance-only diffs to alloy-devices-yml.

## Phase 3: Codegen-side cleanup

- [ ] 3.1 Confirm parity gate green for stm32f4 + stm32g0.
- [ ] 3.2 Delete `alloy_codegen/sources/stm32_open_pin_data.py`.
- [ ] 3.3 Delete the ST scope from `alloy_codegen/sources/cmsis_svd.py`.
- [ ] 3.4 Delete `_build_st_device_ir` from `stages/normalize.py`.
- [ ] 3.5 Remove ST-specific imports the deletion strands.

## Phase 4: Validate + archive

- [ ] 4.1 alloy-codegen: full pytest, parity gate green.
- [ ] 4.2 alloy-data-extractor: pytest + new ST extractor unit tests.
- [ ] 4.3 `openspec validate migrate-stm32-extractor --strict`.
- [ ] 4.4 Archive + commit in both repos.
