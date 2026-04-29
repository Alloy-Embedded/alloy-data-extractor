## ADDED Requirements

### Requirement: The nxp_mcux extractor SHALL emit every CMSIS-SVD register + field

For every iMXRT-family device admitted via the `nxp_mcux`
extractor, the resulting canonical IR's `device.registers` and
`device.register_fields` SHALL include every register declared
in the device's CMSIS-SVD source — no peripheral whitelist, no
size filter — with full `(peripheral, name, offset, access,
size_bits)` for registers and `(peripheral, register_name,
name, bit_offset, bit_width, access)` for fields.  Registers
tagged with `<derivedFrom>` SHALL inherit the source register's
field set rather than appearing as empty rows.

#### Scenario: mimxrt1062 register density matches SVD source

- **WHEN** the nxp_mcux extractor processes mimxrt1062
- **THEN** the resulting canonical IR's `device.registers`
  count SHALL be at least 1500
- **AND** `device.register_fields` count SHALL be at least 6000
- **AND** the LPUART1, LPSPI1, LPI2C1, GPIO1 peripherals SHALL
  each carry at least 10 registers

#### Scenario: alloy-codegen UART traits no longer emit kInvalidRegisterRef

- **WHEN** alloy-codegen emits `uart.hpp` for the regenerated
  mimxrt1062 YAML
- **THEN** the LPUART1 trait specialisation's `kCr1Register`,
  `kBrrRegister`, `kIsrRegister` etc. SHALL resolve to real
  `RuntimeRegisterRef` values (not `kInvalidRegisterRef`)
- **AND** the runtime-cpp-smoke gate SHALL stay green
