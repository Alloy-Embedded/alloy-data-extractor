# Tasks — migrate-nordic-zephyr-extractor

- [ ] 1.1 Split the existing extractor into a package
      `extractors/zephyr_dts/`.
- [ ] 1.2 Port `zephyr_pinctrl.py` into
      `extractors/zephyr_dts/pinctrl.py` (NRF_PSEL +
      STM32_PINMUX decoders).
- [ ] 1.3 Register `Extractor` for `(nordic, nrf52)`.
- [ ] 1.4 Re-extract nrf52840; drift SHALL be zero.
- [ ] 1.5 Confirm parity gate green for nrf52.
- [ ] 1.6 Delete codegen-side `zephyr_dts.py` + `zephyr_pinctrl.py`
      + `_build_zephyr_dts_device_ir`.
- [ ] 1.7 `openspec validate migrate-nordic-zephyr-extractor --strict`.
- [ ] 1.8 Archive + commit in both repos.
