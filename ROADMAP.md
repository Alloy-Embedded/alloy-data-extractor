# alloy-data-extractor — ROADMAP

**Mission.**  Be the single ETL pipeline that produces every
`alloy-devices-yml` entry — across every architecture and vendor
worth supporting — so that `alloy-codegen` (and future siblings:
`alloy-codegen-rust`, `alloy-codegen-zig`, `alloy-codegen-docs`)
consume one canonical schema and emit language-specific
artifacts without re-implementing extraction.

**End state.**  ~8,000 chips covered (Cortex-M, AVR, PIC, RISC-V,
Xtensa, MSP430, 8051) by extractors that all conform to one
`Extractor` protocol, all write canonical YAML byte-identically,
and all run in one CI matrix that publishes a coverage dashboard
to `alloy-devices-yml/index.yml`.

This is a multi-quarter project. The roadmap below breaks it
into 19 OpenSpec changes across 5 phases. Each phase locks an
invariant before the next begins.

---

## Where we are today (April 2026)

| Layer | Status |
|---|---|
| Canonical YAML schema (`vendor.schema.json` + `family.schema.json` + `device.schema.json`) | ✅ Shipped in alloy-devices-yml |
| Codegen consumer (`alloy_codegen.sources.alloy_devices_yml`) | ✅ Shipped |
| Extractor scaffolding (CLI, pipeline, canonical-YAML writer) | ✅ |
| Extractors registered in the protocol registry | ✅ 15 extractors |
| 17 admitted devices: codegen-side parity gate green | ✅ 17/17 pass |
| Bulk-mode (auto-discover chips from cmsis-pack-manager) | ✅ Phase 2.1 archived |
| Cross-source merge (SVD ⊕ open-pin-data ⊕ modm) | ✅ Phase 2.2 archived |
| Coverage index + dashboard | ✅ Phase 2.3 archived |
| Bulk-admitted catalog | ✅ **8,500+ chips** across 22 vendors / 1,180+ families |
| Zephyr DTS pipeline (8 vendors mapped) | ✅ 159/164 chips extract clean |
| PIC / MSP430 / 8051 / community RISC-V | ✅ Real implementations + tests |
| Vendor parsers still living in `alloy-codegen/src/alloy_codegen/sources/` | ⏳ Pending Phase 1 codegen-side cleanup |

**Bulk-admitted catalog breakdown (8,505 chips total):**

* **CMSIS-Pack manager** — 7,700+ chips across 16 vendors (ST,
  SiLabs, Nuvoton, Infineon, Cypress, TI, Renesas, Toshiba,
  ARM, Ambiq, + 7 community vendors).  Pulls per-chip pack
  zips on demand, extracts SVD, cross-references catalog
  metadata for accurate core/memory.
* **STM32 cross-source merge** — 503 chips (CMSIS-SVD ⊕ STM32
  open-pin-data ⊕ optionally modm-devices).  Schema_version
  1.3.0 with per-field provenance.
* **Zephyr DTS** — 159 chips across nordic / atmel / ambiq /
  silabs / ti families (cpp-preprocessed `.dtsi` → dtlib).
* **Vendor-direct extractors** — 17 admitted + 47 Microchip
  ATDF + 8 Espressif + 2 NXP iMXRT.

**Moat target hit.**  The original ROADMAP set ~8,000 chips
as the "single OSS framework covering PIC + AVR + ARM + RISC-V
+ Xtensa simultaneously" goal.  At 8,505 chips the catalog
exceeds that target.

Total active extractors: **15** (cmsis-pack, cmsis-svd,
datasheet-pdf, esp-idf, intel-8051, microchip-dfp, microchip-pic,
modm-devices, msp430, nxp-mcux, pico-sdk, stm32, stm32-cubemx,
stm32-open-pin-data, zephyr-dts).

---

## Phase 0 — Foundation hardening *(3 OpenSpecs, ~3 sprints)*

**Goal.**  Lock the invariants that everything downstream relies on.

| ID | OpenSpec | Outcome |
|---|---|---|
| 0.1 | `lock-canonical-yaml-schema-v1` | Schema is versioned (`schema_version: 1.x.x`); both extractor and codegen reject YAMLs that don't validate; CI fails on schema violation in any committed YAML. |
| 0.2 | `define-extractor-protocol` | Single Python `Protocol` (`Extractor`) every extractor implements; `extract_device(...)` signature, source-pin contract, provenance shape; pipeline dispatches generically. |
| 0.3 | `add-codegen-yaml-parity-gate` | For each of the 17 admitted devices, the IR loaded from YAML must be byte-identical to the IR built by the legacy `_build_*_device_ir` path; gate runs in alloy-codegen CI. **Required before any vendor migrates.** |

**Exit criteria.**  Schema is locked at v1, extractor protocol
is enforced, and codegen has a green parity gate for all 17
devices. Now safe to start removing legacy paths.

---

## Phase 1 — Migrate codegen `sources/` → extractor *(7 OpenSpecs, ~6 sprints)*

**Goal.**  Move every vendor parser from alloy-codegen into
alloy-data-extractor. After this phase, `alloy-codegen/src/alloy_codegen/sources/`
contains only `alloy_devices_yml.py` (the YAML reader) + `raw.py`
(shared types). `normalize.py` becomes a thin YAML→IR projection.

Each migration is one OpenSpec, scoped to one vendor:

| ID | OpenSpec | Sources moved | LOC | Devices affected |
|---|---|---|---|---|
| 1.1 | `migrate-stm32-extractor` | `cmsis_svd` (ST scope) + `stm32_open_pin_data` | ~640 | stm32f4 (2), stm32g0 (3) |
| 1.2 | `migrate-microchip-dfp-extractor` | `microchip_dfp` (ATDF for AVR + SAM) | ~1,053 | avr-da (1), same70 (2) |
| 1.3 | `migrate-nxp-mcux-extractor` | `nxp_mcux` | ~243 | imxrt1060 (2) |
| 1.4 | `migrate-espressif-esp-idf-extractor` | `esp_idf` | ~258 | esp32 (2), esp32c3 (1), esp32s3 (1) |
| 1.5 | `migrate-rp2040-pico-sdk-extractor` | `pico_sdk` | ~182 | rp2040 (2) |
| 1.6 | `migrate-nordic-zephyr-extractor` | `zephyr_dts` codegen-side + `zephyr_pinctrl` | ~885 | nrf52 (1) |
| 1.7 | `migrate-modm-enrichment-extractor` | `modm_devices` | ~529 | cross-cutting (STM32 enrichment) |

**Per-vendor migration recipe:**
1. Port the parser into `alloy-data-extractor/src/alloy_data_extractor/extractors/<vendor>.py`.
2. Wire it into `_EXTRACTORS` registry.
3. Re-extract every admitted device of that vendor → write fresh YAML to alloy-devices-yml.
4. Run the parity gate (Phase 0.3) — must stay green.
5. Delete the codegen-side `sources/<vendor>.py` and the matching `_build_<vendor>_device_ir` from `normalize.py`.
6. Codegen uses `alloy_devices_yml.load_canonical_device(...)` for that vendor exclusively.

**Exit criteria.** alloy-codegen `sources/` reduced to 2 files.
All 17 admitted devices flow `vendor pack → extractor → YAML →
codegen` end-to-end.

---

## Phase 2 — Bulk-mode infrastructure *(3 OpenSpecs, ~4 sprints)*

**Goal.** Stop hand-curating `(vendor, family, device)` tuples.
The extractor discovers chips automatically, merges multi-source
data deterministically, and reports coverage continuously.

| ID | OpenSpec | Outcome |
|---|---|---|
| 2.1 | `add-bulk-discovery-cmsis-pack-manager` | `alloy-data-extract bulk --vendor st` discovers every chip in the vendor's CMSIS-Pack catalog, runs the right extractor per family, writes one YAML per chip. ~5,000 ARM chips become extractable in one CLI invocation. |
| 2.2 | `add-cross-source-merge` | When a chip has data from multiple sources (e.g. STM32 has CMSIS-SVD ⊕ STM32CubeMX ⊕ modm-devices ⊕ Zephyr DTS), merge deterministically with a documented priority order. Per-field provenance preserved. |
| 2.3 | `add-coverage-index-and-dashboard` | `alloy-devices-yml/index.yml` is the catalog of every `(vendor, family, device)` triple with its source provenance. CI publishes a Markdown matrix (vendor × source × chip count, weekly drift). |

**Exit criteria.** `alloy-data-extract bulk --vendor X` works
for all migrated vendors; `index.yml` is the single source of
truth for coverage; dashboard updates daily.

---

## Phase 3 — Coverage expansion to ~8,000 chips *(4 OpenSpecs, ~6 sprints)*

**Goal.** Cover the architectures no other OSS HAL framework
covers — PIC, full STM32 Cube DB, MSP430, non-ESP RISC-V.

| ID | OpenSpec | Source | Chips |
|---|---|---|---|
| 3.1 | `add-microchip-pic-extractor` | MPLAB X DFP packs (`.atpack`) | PIC8/16/18 (~1,500) + PIC24/dsPIC33 (~500) + PIC32 (~150) = **~2,150** |
| 3.2 | `add-stm32-cubemx-db-extractor` | STM32CubeMX MCU DB (XML) | Full STM32 catalog (~1,500), with pinmux tables + clock tree edges that CMSIS-SVD lacks |
| 3.3 | `add-msp430-extractor` | TI SysConfig + MSP430 datasheet headers | ~200 |
| 3.4 | `add-riscv-community-svd-extractor` | GD32V, BL602/702, CH32V, K210, etc. SVDs | ~80 |

**Exit criteria.** `alloy-devices-yml` carries data for
~8,000 chips; the project becomes the **only OSS HAL framework
covering PIC + AVR + ARM + RISC-V + Xtensa simultaneously** with
shared schema.

---

## Phase 4 — Stretch architectures *(2 OpenSpecs, opportunistic)*

**Goal.** Last-resort coverage for vendors with no machine-readable source.

| ID | OpenSpec | Approach | Chips |
|---|---|---|---|
| 4.1 | `add-modm-data-pdf-extractor` | Datasheet PDF scraping (modm-data style) for chips whose vendor publishes no SVD/ATDF/DTS | Long tail |
| 4.2 | `add-8051-extractor` | Nuvoton, SiLabs, STC vendor SDKs | ~150 |

These are opportunistic — they land when contributors push them,
not on a fixed schedule.

---

## Cross-cutting invariants (every OpenSpec must respect)

1. **Determinism.** Same input pins → byte-identical YAML output.
2. **Provenance.** Every value in YAML carries `provenance.source_id` (which extractor) + `provenance.revision` (which pin). No anonymous data.
3. **Schema-validated.** Every YAML written is validated against `device.schema.json` before commit.
4. **Parity-gated.** Extractor changes that affect already-admitted devices must keep the codegen parity gate green.
5. **Pin-versioned.** Every upstream source (vendor pack, repo) has an entry in `data/source_pins.toml` with `revision` + `origin_url` + `license`.
6. **One extractor, one source format.** No extractor bridges two source formats; merging multi-source data is the job of `add-cross-source-merge` (Phase 2.2).

---

## Estimated timeline (best-case)

| Phase | Specs | Duration | Cumulative |
|---|---|---|---|
| Phase 0 | 3 | 3 sprints | 1.5 months |
| Phase 1 | 7 | 6 sprints | 4.5 months |
| Phase 2 | 3 | 4 sprints | 6.5 months |
| Phase 3 | 4 | 6 sprints | 9.5 months |
| Phase 4 | 2 | open-ended | 12+ months |

Phases 0 and 1 are critical-path; phases 2-4 can parallelise
once the protocol is locked.

---

## OpenSpec index

The 19 OpenSpec changes for this roadmap live under
`openspec/changes/<change-id>/`. They are listed in execution
order; later phases depend on earlier ones. Phase 4 is opportunistic.

```
openspec/changes/
  lock-canonical-yaml-schema-v1/
  define-extractor-protocol/
  add-codegen-yaml-parity-gate/
  migrate-stm32-extractor/
  migrate-microchip-dfp-extractor/
  migrate-nxp-mcux-extractor/
  migrate-espressif-esp-idf-extractor/
  migrate-rp2040-pico-sdk-extractor/
  migrate-nordic-zephyr-extractor/
  migrate-modm-enrichment-extractor/
  add-bulk-discovery-cmsis-pack-manager/
  add-cross-source-merge/
  add-coverage-index-and-dashboard/
  add-microchip-pic-extractor/
  add-stm32-cubemx-db-extractor/
  add-msp430-extractor/
  add-riscv-community-svd-extractor/
  add-modm-data-pdf-extractor/
  add-8051-extractor/
```
