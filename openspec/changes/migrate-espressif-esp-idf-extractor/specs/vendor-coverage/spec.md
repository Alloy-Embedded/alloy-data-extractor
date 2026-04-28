## ADDED Requirements

### Requirement: alloy-data-extractor SHALL own ESP-IDF extraction for the Espressif family

The extractor SHALL register one `esp-idf` `Extractor` covering `(espressif, esp32)`, `(espressif, esp32c3)`, and `(espressif, esp32s3)`.  Dual-core control-plane facts (PRO_CPU + APP_CPU) SHALL continue to be emitted for ESP32 and ESP32-S3.  After this change archives, alloy-codegen SHALL contain no Espressif-specific parsing logic.

#### Scenario: Dual-core ESP32 admitted with PRO_CPU + APP_CPU bring-up

- **WHEN** the pipeline runs for an ESP32 dual-core device
- **THEN** the canonical IR carries the `bring_up_app_cpu()` startup descriptor for APP_CPU
- **AND** the parity gate SHALL stay green for esp32, esp32c3, esp32s3
- **AND** alloy-codegen SHALL contain no `_build_esp32_device_ir` callable
