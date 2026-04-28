## ADDED Requirements

### Requirement: alloy-data-extractor SHALL ingest the STM32CubeMX MCU database as an enrichment source

The extractor SHALL register a secondary `EnrichmentExtractor` named `stm32-cubemx` that consumes the STM32CubeMX MCU database (`db/mcu/*.xml`) and produces enrichment records carrying alternate-function tables, clock-tree edges, and DMA request-id mappings.  When merged via `MergePolicy.STM32`, CubeMX SHALL be the authoritative source for `pins[*].alternate_functions`, `clock_nodes`, and `dma_requests` on STM32 chips.

#### Scenario: STM32 pinmux loads CubeMX alternate-function tables

- **WHEN** the merged extraction runs for `stm32g071rb` with CubeMX as enrichment
- **THEN** the YAML's `pins[*].alternate_functions` field SHALL carry the AF tuples CubeMX defined for each pin
- **AND** every AF entry's `_provenance.source_id` SHALL equal `stm32-cubemx`

### Requirement: The CubeMX database SHALL be supplied externally, not bundled

The extractor SHALL refuse to bundle the CubeMX MCU database in the repository.  The user SHALL supply the path via `--source stm32cubemx-db=<path>` or the matching environment variable.  The pin entry in `data/source_pins.toml` SHALL record the supported CubeMX version (e.g. `v6.10.0`) without distributing the binary.

#### Scenario: Missing CubeMX path raises a clear error

- **WHEN** the STM32 extractor is invoked with `MergePolicy.STM32` enabled but no `stm32cubemx-db` source path provided
- **THEN** the extractor SHALL raise `MissingSourceError`
- **AND** the message SHALL instruct the user to install CubeMX and pass `--source stm32cubemx-db=<path>`
