# DEFERRED — proposal premise needs revision + multi-source coordination

## Why this archives without implementation

The proposal's central claim — that
`dts/bindings/<peripheral>/nordic,*.yaml` "declares the
per-peripheral register layout (offsets, fields, access)" — is
not accurate.  Inspection of files like
`zephyr/dts/bindings/serial/nordic,nrf-uarte.yaml` confirms
they describe **device-tree property contracts** (e.g.
`endtx-stoptx-supported: bool`, `default-gpio-port: phandle`)
rather than register layouts.  Register-level data for nRF52840
lives in:

- The Nordic-supplied CMSIS-SVD or Pack file
  (`Nordic.nRF_DeviceFamilyPack`), *not* cached locally.
- The Nordic MDK headers (`nrf52840_bitfields.h`,
  `nrf52840_peripherals.h`), also not in tree.

Zephyr cached at `/Users/lgili/Documents/01 - Codes/01 - Github/zephyr`
*does* carry useful artefacts for this device:

- `zephyr/dts/arm/nordic/nrf52840.dtsi` — peripheral instance
  list + base addresses + interrupts (already extracted by the
  existing `zephyr_dts` extractor).
- `zephyr/include/zephyr/dt-bindings/clock/nrf_clock.h` — clock
  enum constants.
- `zephyr/dts/bindings/clock/nordic,*.yaml` — clock-binding
  contracts.

But the register-tree gap (the proposal's primary motivation)
needs the Nordic SVD or MDK headers, neither of which is
locally cached.

## What's needed before this can land

- **Refocus the proposal**: split the planned work into two
  changes —
  1. `add-nordic-svd-extractor` (or extend cmsis-svd to admit
     the Nordic Pack-supplied SVD): drives the register-tree
     gap.
  2. `extract-nrf52840-clock-tree-from-zephyr-bindings`: drives
     the clock-graph gap purely from Zephyr DTS data, where
     the data really is.
- Cache the Nordic CMSIS-Pack (`Nordic.nRF_DeviceFamilyPack`)
  via cmsis-pack-manager, then run the existing cmsis-svd
  walker against the unpacked SVD.  Expected result: the
  nrf52840 YAML's register count goes from 0 to several
  hundred (consistent with other Cortex-M4 YAMLs).
- Tier 2/3/4 backfill from the Nordic PDF (`nRF52840_PS.pdf`)
  reuses the existing `datasheet-pdf` extractor — but the
  fixture path the proposal references
  (`tests/fixtures/nordic/nRF52840_PS.pdf`) is not in tree
  either; the PDF needs to be added explicitly.

## Where to look next

* `extractors/zephyr_dts.py` — handles the dtsi peripheral
  extraction today.
* `extractors/cmsis_svd.py` — gained a register-tree projection
  in commit `18fd166`; would do the heavy lifting once a Nordic
  SVD is staged.
* `extractors/datasheet_pdf.py` — the path for tier-2/3/4
  backfill from the Nordic PDF.
