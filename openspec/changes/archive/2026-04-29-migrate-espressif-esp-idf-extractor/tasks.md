# Tasks — migrate-espressif-esp-idf-extractor

- [ ] 1.1 Port `esp_idf.py` into `extractors/esp_idf.py`,
      register `Extractor` for esp32, esp32c3, esp32s3.
- [ ] 1.2 Preserve dual-core control-plane (PRO_CPU/APP_CPU)
      bring-up emission for ESP32 + ESP32-S3.
- [ ] 1.3 Per-device DPORT clock-gate manual overrides remain
      data-driven (not hardcoded).
- [ ] 1.4 Re-extract all 4 admitted Espressif devices; drift
      SHALL be zero.
- [ ] 1.5 Confirm parity gate green; delete codegen-side parser
      + `_build_esp32_device_ir`.
- [ ] 1.6 `openspec validate migrate-espressif-esp-idf-extractor --strict`.
- [ ] 1.7 Archive + commit in both repos.
