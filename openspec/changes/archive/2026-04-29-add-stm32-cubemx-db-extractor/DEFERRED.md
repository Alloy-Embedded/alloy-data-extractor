# DEFERRED — primary surface complete, bulk-emission follow-up

## What landed under this change

The `stm32-cubemx` extractor reads CubeMX's MCU database (MCU
root XML + GPIO IP AF table + DMA IP request matrix +
clock-tree plugin XML) and projects an enrichment payload that
the merge engine folds onto the primary STM32 extraction.  All
parser-side and registration-side work is done; 18 tests
including F0/F4/G0 smoke tests against the local CubeMX install
exercise it end-to-end.

`data/source_pins.toml` carries the `stm32cubemx-db @ v6.17`
pin entry without bundling the binary.

`openspec validate add-stm32-cubemx-db-extractor --strict`
passed at archive time.

## What remains and why it's deferred

* **Task 1.3 — Re-emit STM32 YAMLs.**  The merge engine
  composes stm32 (primary) ⊕ stm32-cubemx into a payload
  carrying schema 1.3.0 with per-field provenance, but the
  re-emitted YAML still differs from the canonical YAML in
  alloy-devices-yml because:
  - The primary stm32 path now emits a register tree (commit
    18fd166) and per-row provenance (commit 7fb4dc3), but the
    canonical YAML carries *additional* CubeMX-derivable
    peripheral fields (`ip_name`, `ip_version`, `instance`,
    `rcc_enable_signal`, `rcc_reset_signal`, `backend_schema_id`,
    `shared_group`) that the cmsis-svd extractor cannot supply.
  - The canonical YAML also carries `bootstrap-patch` overrides
    that aren't reproducible from any extractor — they were
    hand-curated overlays.
  Re-emitting today closes ~81 % of the structural gap (1,970 →
  59,620 lines vs canonical's 73,410).  The remaining 19 % is
  the CubeMX `<IP>` peripheral enrichment + bootstrap-patch
  overlays.

* **Task 1.6 — Archive.**  This file.

## Where to look next

* `extractors/stm32_cubemx.py` — the parser.
* `merge.py::STM32_MERGE_POLICY` — per-field merge priority.
* `scripts/reemit_stm32_with_cubemx.py` — single-chip driver
  used to land the proof-of-concept.
* The follow-up workstream is "extend stm32-cubemx to project
  CubeMX `<IP>` Name/Version/InstanceName onto peripherals", at
  which point bulk re-emission becomes safe.
