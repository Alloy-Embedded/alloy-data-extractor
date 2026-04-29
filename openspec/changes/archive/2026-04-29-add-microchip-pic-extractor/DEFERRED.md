# DEFERRED — primary surface + per-arch IR complete, bulk admission follow-up

## What landed under this change

`extractors/microchip_pic.py` admits PIC8/16/18 + PIC24/dsPIC33
+ PIC32MX/MZ/MK families.  It reuses the Phase 1.2
`microchip-dfp` ATDF parser and adds per-arch carve-outs under
`payload.arch_extensions`:

* `banked_memory` — PIC8/16/18 BANK<N>_GPR/SFR/RAM/MIRROR rows.
* `indirect_pointer_registers` — PIC24/dsPIC33 W0..W15 + TBLPAG
  / DSRPAG / DSWPAG / PSVPAG / NVMSRCADRL/H / RPINR0.
* `dsp_sfrs` — dsPIC33 CORCON / ACCAx / DCOUNT / DOSTART /
  DOEND / MODCON / XMODSRT / YMODEND / XBREV.
* `cp0_registers` — PIC32 MIPS Coprocessor-0 registers from
  `<address-space id="cp0">`.

The shared `_memory_regions()` helper in `microchip_dfp.py`
projects all ATDF address-spaces with canonical-YAML keys
(`base_address` / `size_bytes` / `access` / `address_space`).

17 tests across all 8 admitted PIC families.  `openspec validate
add-microchip-pic-extractor --strict` passed at archive time.

## What remains and why it's deferred

* **Phase 4 — Bulk admission (~2,150 chips).**
  - 4.1 PIC8/16/18 (~1,500 chips)
  - 4.2 PIC24/dsPIC33 (~500)
  - 4.3 PIC32MX/MZ/MK (~150)
  - 4.4 YAML PRs to alloy-devices-yml.

  Blocked at archive time on local data availability: the
  PHASE_1_HANDOFF.md notes Microchip DFP downloads as
  SSL-blocked on this workstation.  The PIC packs need to be
  fetched from `packs.download.microchip.com` (TLS chain that
  the local store rejects) on a machine with proper certs, or
  a pre-fetched cache must be staged.

* **Phase 5.3 — Archive.**  This file.

## Where to look next

* `extractors/microchip_pic.py` — the per-arch IR projection.
* `extractors/microchip_dfp.py::_memory_regions` — the shared
  ATDF address-space walker, also exercised by AVR-DA + SAM E70.
* `data/source_pins.toml::microchip-mplab-x-dfp` — the pin
  entry awaiting a real revision once DFP fetch is unblocked.
