# Complete iMXRT1060 Register Coverage

## Why

The `mimxrt1062` and `mimxrt1064` YAMLs in alloy-devices-yml
admit 28-29 peripherals each but ship only **49-53 registers
and ~50 register fields total** — that's **1.8 registers per
peripheral**.  For comparison, Espressif's esp32 (46
peripherals) ships 1882 registers / 7406 fields, and SAME70
(63 peripherals) ships 1230 / 10619.

The CMSIS-SVD source for the i.MX RT1060 family
(`MIMXRT1062.svd` from NXP MCUXpresso SDK) is the canonical
shape — every UART register, every LPSPI register, every IOMUX
slot is in there.  The current `nxp_mcux` extractor only emits
a thin slice (peripheral instances + base addresses + one or
two registers per peripheral).

Result: every emitted iMXRT trait header has `kPresent=true`
but `RuntimeRegisterRef kCr1Register = kInvalidRegisterRef;`
because the IR's `device.registers` doesn't carry the actual
register entries.  Drivers can't read/write registers on
iMXRT today without falling back to raw pointers.

## What Changes

- Audit the `nxp_mcux` extractor's register-walking step.
  Identify which SVD `<peripheral>` `<registers>` blocks are
  being skipped vs emitted today.
- Extend the SVD parser to include every register's
  `<fields>` block (currently dropped).
- Project parsed registers onto the canonical IR's
  `device.registers` and `device.register_fields` tuples with
  full provenance (`source_id="nxp-mcux-soc-svd"`).
- Re-extract YAMLs for `mimxrt1062` + `mimxrt1064`.  Expected
  delta: 49 registers → ~1500 registers per device, 50 fields
  → ~6000 fields per device (in line with Espressif / SAME70
  density).
- Verify the regenerated YAML produces a working `uart.hpp` /
  `lpspi.hpp` etc. via the alloy-codegen smoke-compile gate.

## Impact

iMXRT lifts from Grade C ("registers critically thin") to
Grade B in the alloy-devices-yml audit.  Every alloy HAL
driver (UART / SPI / I2C / GPIO / DMA / PWM / Timer) gains
register-level write access on the i.MX RT1060 family without
new patches.

Downstream: emitted `uart.hpp` for mimxrt1062 stops emitting
`kInvalidRegisterRef` for `kCr1Register`, `kBrrRegister`, etc.
The runtime-cpp-smoke gate covers the new shape automatically.

## What this DOES NOT do

- Does not extend coverage to other NXP families
  (MIMXRT1170, MIMXRT500, KW3x).  Each of those ships its own
  SVD; admitting them is a separate
  `add-mimxrt1170-target`-shaped change.
- Does not bake IOMUXC pin-routing data — that comes from the
  `MIMXRT1062.h` header, not the SVD.  IOMUX is already partly
  populated and is out of scope here.
- Does not change the canonical IR schema.  Every field
  consumed already exists on `CanonicalDeviceIR.registers` and
  `CanonicalDeviceIR.register_fields`.
