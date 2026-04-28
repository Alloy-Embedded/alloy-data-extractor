## ADDED Requirements

### Requirement: alloy-data-extractor SHALL own NXP MCUXpresso extraction

The extractor SHALL register one `nxp-mcux` `Extractor` covering `(nxp, imxrt1060)`.  The two admitted iMXRT devices (`mimxrt1062`, `mimxrt1064`) SHALL flow through this extractor exclusively after the change archives.  alloy-codegen SHALL contain no NXP-specific parsing logic and no `_build_nxp_device_ir` callable.

#### Scenario: iMXRT devices admitted via the extractor

- **WHEN** the pipeline runs for `mimxrt1062`
- **THEN** the canonical IR loads from `vendors/nxp/imxrt1060/devices/mimxrt1062.yml`
- **AND** the parity gate SHALL stay green for both iMXRT variants
- **AND** alloy-codegen SHALL contain no `nxp_mcux` module
