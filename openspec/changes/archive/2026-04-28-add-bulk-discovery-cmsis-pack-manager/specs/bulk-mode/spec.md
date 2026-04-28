## ADDED Requirements

### Requirement: alloy-data-extractor SHALL discover and extract entire vendor catalogs in one CLI invocation

The extractor SHALL ship a `bulk` CLI subcommand that walks a vendor's CMSIS-Pack catalog (via `cmsis-pack-manager`), discovers every device in that catalog, dispatches each through the appropriate registered `Extractor`, and writes one canonical YAML per device into alloy-devices-yml.  Per-chip failures SHALL NOT halt the run; they SHALL be collected into a `bulk-report.json` listing each chip with its status (`PASS`, `EXTRACT_FAILED`, `SCHEMA_INVALID`, `NO_EXTRACTOR_REGISTERED`).

#### Scenario: Bulk run for ST writes hundreds of YAMLs deterministically

- **WHEN** `alloy-data-extract bulk --vendor st` is run against a pinned cmsis-pack-manager catalog
- **THEN** the command SHALL discover every ST chip in that catalog
- **AND** SHALL write one YAML per chip under `vendors/st/<family>/devices/<device>.yml`
- **AND** running the command twice with the same pin SHALL produce byte-identical YAMLs

#### Scenario: One chip's failure does not abort the run

- **WHEN** a bulk run hits a chip whose extractor raises `MissingSourceError`
- **THEN** the chip's status in `bulk-report.json` SHALL be `EXTRACT_FAILED` with the error message
- **AND** the run SHALL continue with the remaining chips
- **AND** the command's exit code SHALL be 0 if the report is the only failure surface

### Requirement: Bulk runs SHALL support sharding for CI parallelism

The `bulk` subcommand SHALL accept `--shard N/M` to extract only the Nth of M deterministic shards of the discovered chip set, so CI can fan out a large vendor across multiple jobs.

#### Scenario: Shard partition is deterministic and exhaustive

- **WHEN** `alloy-data-extract bulk --vendor st --shard 1/8` and `... --shard 2/8` … `... --shard 8/8` are all run
- **THEN** the union of YAMLs written across the 8 shards SHALL equal the YAMLs an unsharded run would write
- **AND** no chip SHALL appear in more than one shard
