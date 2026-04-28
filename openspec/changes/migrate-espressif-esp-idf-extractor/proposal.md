# Migrate Espressif ESP-IDF Extraction into alloy-data-extractor

## Why

`alloy-codegen/src/alloy_codegen/sources/esp_idf.py` (258 LOC)
parses ESP-IDF SOC headers and feeds 4 admitted Espressif devices:
ESP32 (Xtensa LX6 dual-core), ESP32-C3 (RISC-V RV32IMC), ESP32-S3
(Xtensa LX7 dual-core).  Espressif is the only Xtensa + RISC-V
vendor in the admitted set; the migration unblocks future ESP32
variants (S2, C6, P4, H2) via `add-bulk-discovery-cmsis-pack-manager`.

## What Changes

- New extractor `alloy_data_extractor.extractors.esp_idf`
  registered for `(espressif, esp32)`, `(espressif, esp32c3)`,
  `(espressif, esp32s3)`.
- Dual-core control-plane facts (PRO_CPU + APP_CPU bring-up
  registers) preserved; ADC factory-calibration delegation to
  esp-idf runtime continues to be a documented carve-out.
- ESP32 partial-SVD compensation (the manual DPORT clock-gate
  patches) moves into the extractor as overrideable per-device
  hooks.
- alloy-codegen: delete `sources/esp_idf.py` and
  `_build_esp32_device_ir`.

## Impact

- alloy-data-extractor: +~258 LOC.
- alloy-codegen: -~258 LOC parser.
- alloy-devices-yml: 4 YAMLs rewritten byte-identical.
- Footprint: ESP32 device-sidecar is large (~600KB);
  `artifact-footprint-budget` headroom in alloy-codegen
  already accommodates this.

## What this does NOT do

- Does not extend SVD coverage for ESP32 UART1/UART2/SPI2/etc.
  (upstream SVD remains partial; documented in alloy-devices README).
- Does not implement esp-idf's runtime ADC calibration —
  delegated as today.
