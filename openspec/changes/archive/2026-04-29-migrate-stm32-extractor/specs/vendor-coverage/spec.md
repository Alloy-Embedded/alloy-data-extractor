## ADDED Requirements

### Requirement: alloy-data-extractor SHALL own STM32 extraction end-to-end

The extractor SHALL register a single `stm32` `Extractor` covering `(st, stm32f4)` and `(st, stm32g0)`.  This extractor SHALL consume CMSIS-SVD + STM32 open-pin-data and produce canonical YAML byte-identical to what alloy-codegen's legacy `_build_st_device_ir` produced for the 5 admitted ST devices at the time of this change.  After this change archives, alloy-codegen SHALL contain no ST-specific parsing logic — every ST device SHALL flow `extractor → YAML → codegen consumer`.

#### Scenario: Admitted ST devices flow through the extractor

- **WHEN** the pipeline runs for `stm32g071rb`
- **THEN** the canonical IR SHALL load from `vendors/st/stm32g0/devices/stm32g071rb.yml`
- **AND** the codegen path `_build_st_device_ir` SHALL no longer exist
- **AND** the parity gate from `add-codegen-yaml-parity-gate` SHALL stay green

#### Scenario: alloy-codegen no longer imports ST-specific parsers

- **WHEN** alloy-codegen is grepped for `stm32_open_pin_data` or `_build_st_device_ir`
- **THEN** zero matches SHALL be found in `src/alloy_codegen/`
