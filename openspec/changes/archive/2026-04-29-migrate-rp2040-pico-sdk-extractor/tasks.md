# Tasks — migrate-rp2040-pico-sdk-extractor

- [ ] 1.1 Port `pico_sdk.py` into `extractors/pico_sdk.py`,
      register `Extractor` for `(raspberrypi, rp2040)`.
- [ ] 1.2 Preserve single-core-perspective bring-up.
- [ ] 1.3 Re-extract `pico` + `rp2040`; drift SHALL be zero.
- [ ] 1.4 Confirm parity gate green; delete codegen-side parser
      + `_build_rp2040_device_ir`.
- [ ] 1.5 `openspec validate migrate-rp2040-pico-sdk-extractor --strict`.
- [ ] 1.6 Archive + commit in both repos.
