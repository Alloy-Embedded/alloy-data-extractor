## ADDED Requirements

### Requirement: alloy-data-extractor SHALL deterministically merge multi-source data per chip

The extractor SHALL ship a `merge` engine that folds enrichment records (from secondary `EnrichmentExtractor` instances) onto a primary extraction payload according to a declared, human-readable `MergePolicy` per family.  The merged output SHALL be deterministic: same inputs + same policy → byte-identical YAML.  Every merged field SHALL carry per-field provenance recorded under `provenance.field_provenance` so reviewers can audit which source supplied each value.

#### Scenario: STM32 merge composes CMSIS-SVD, modm, and CubeMX

- **WHEN** the STM32 extractor runs for `stm32g071rb` with CMSIS-SVD as primary plus modm-devices and CubeMX as enrichments
- **THEN** the merged payload's `peripherals[*].base_address` carries `_provenance.source_id = "cmsis-svd-data"`
- **AND** `peripherals[*].dma_bindings` carries `_provenance.source_id = "modm-devices"` (when modm provides the binding)
- **AND** `pins[*].alternate_functions` carries `_provenance.source_id = "stm32cubemx"` when CubeMX is present, otherwise the modm value

### Requirement: Field provenance SHALL be schema-versioned

The canonical YAML schema SHALL bump to `1.3.0` and add an optional `provenance.field_provenance` field — a mapping from `source_id` to a list of dotted JSON-Pointer paths the source supplied.  Pre-1.3.0 YAMLs SHALL continue to validate (the field is optional).

#### Scenario: Older YAMLs without field_provenance still validate

- **WHEN** a YAML pinned at `schema_version: 1.2.0` is validated against the v1.3.0 schema
- **THEN** validation SHALL succeed
- **AND** `field_provenance` SHALL be treated as absent rather than empty
