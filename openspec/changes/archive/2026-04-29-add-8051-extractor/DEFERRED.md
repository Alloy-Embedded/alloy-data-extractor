# DEFERRED — primary surface + Phase 2 extensions complete, bulk admission follow-up

## What landed under this change

`extractors/intel_8051.py` parses SDCC-flavored 8051 SFR headers
across Nuvoton N76/N79, SiLabs EFM8, and STC15W.

* `__sfr __at (0x80) NAME;` / `sfr at 0x80 NAME;` /
  `sfr16 __at (...) NAME;` / `__sbit __at (0x80) NAME;` —
  all four declaration forms.
* Phase 2.1 — SFR bank/page tracking driven by `// SFR Page <n>`
  comments and `#pragma sfr_bank/sfr_page <n>` directives.
  Same-address SFRs in different banks stay distinct (N76/N79/
  EFM8 routinely reuse 0xC1 across pages).
* Phase 2.2 — SDCC keyword decorators (`__data`/`__idata`/
  `__xdata`/`__pdata`/`__bdata`) on a declaration stamp
  `addressing_mode` on the projected register row.  Bit
  registers default to `"bit"`.
* `identity.core: i8051`.

16 tests covering header-format variants + bank tracker +
addressing-mode decorators.  `openspec validate
add-8051-extractor --strict` passed at archive time.

## What remains and why it's deferred

* **Task 2.3 — Bulk-extract one chip per vendor with vendor-
  supplied headers; commit YAMLs.**
  Blocked at archive time on local availability of vendor SDK
  header bundles (Nuvoton BSP, SiLabs Configurator headers,
  STC SDK).  Each vendor ships SDCC headers under a slightly
  different layout and needs to be fetched + staged before
  bulk extraction can run.

* **Task 3.3 — Archive.**  This file.

## Where to look next

* `extractors/intel_8051.py` — the parser.
* The future per-vendor SDK fetch + `alloy-data-extract bulk`
  invocation.
