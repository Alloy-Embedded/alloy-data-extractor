## ADDED Requirements

### Requirement: alloy-data-extractor SHALL own modm-devices XML enrichment

The extractor SHALL register a `modm-devices` `EnrichmentExtractor` that consumes modm-devices XML and produces an `EnrichmentRecord` carrying DMA bindings, clock nodes, and alternate-function tables that CMSIS-SVD does not provide.  This extractor SHALL NOT produce its own canonical YAML output; it composes with primary extractors (CMSIS-SVD-for-STM32) to enrich their output.  After this change archives, alloy-codegen SHALL contain no `modm_devices` module.

#### Scenario: STM32 YAMLs continue to carry modm-derived fields

- **WHEN** the pipeline runs for `stm32g071rb` after this change
- **THEN** the canonical IR loaded from YAML SHALL carry the same `dma_bindings` and `clock_nodes` surface that modm enrichment populated under the legacy path
- **AND** the parity gate SHALL stay green for all STM32 admitted devices
