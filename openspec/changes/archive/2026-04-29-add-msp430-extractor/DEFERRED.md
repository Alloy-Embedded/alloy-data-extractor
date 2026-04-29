# DEFERRED — primary surface + Phase 2 extensions complete, bulk admission follow-up

## What landed under this change

`extractors/msp430.py` parses TI MSP430 vendor headers
(msp430-gcc / Code Composer Studio).  Surface:

* Address-of-register defines (`#define <NAME>_  0x...`) become
  one register row, grouped by peripheral prefix (P1, UCA0, …).
* Phase 2.1 — 16-bit width inference: explicit `sfrb`/`sfrw`
  declarations preferred, with a conservative name-pattern
  fallback for headers that omit them (TIMER A/B, WDT,
  ADC10/12, MPY32, USCI 16-bit).
* Phase 2.2 — Pin-port discovery from `PxIN`, with mux arity
  classified as 0/1/2 bits depending on which `PxSEL*`
  registers are present.  AF→peripheral mapping is
  datasheet-only and stays out of scope.
* `identity.core: msp430` set explicitly.

`data/source_pins.toml::ti-msp430-headers @ msp430-gcc-9.3.1.11`
pin entry added.

19 tests covering width inference + pin-port classification +
SFR address parsing.  `openspec validate add-msp430-extractor
--strict` passed at archive time.

## What remains and why it's deferred

* **Task 2.4 — Bulk-extract a representative slice (~20 chips
  per series) and commit YAMLs to alloy-devices-yml.**
  Blocked on local availability of the TI MSP430 GCC header
  bundle.  The header chain ships under
  `<msp430-gcc>/include/msp430` and needs to be staged before
  bulk extraction can run.

* **Task 3.3 — Archive.**  This file.

## Where to look next

* `extractors/msp430.py` — the parser.
* `data/source_pins.toml::ti-msp430-headers` — pin entry awaiting
  a populated cache.
* The future `alloy-data-extract bulk --vendor ti --family
  msp430` invocation once `msp430-gcc` is unpacked locally.
