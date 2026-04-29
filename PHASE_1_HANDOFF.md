# Phase 1 Handoff Notes

This document captures the state after the multi-session
autonomous push that closed Phase 0 + Phase 2 + most of
Phase 3-4, plus large-scale bulk admission.

## Status snapshot (April 2026)

### Phase 0 — Foundation ✅ Archived (3/3)

| Spec | Repos touched |
|---|---|
| `lock-canonical-yaml-schema-v1` | extractor + codegen + alloy-devices-yml |
| `define-extractor-protocol` | extractor |
| `add-codegen-yaml-parity-gate` | codegen |

Codegen parity gate: **17/17 pass** (was 11 pass + 4 xfail + 2 skip).

### Phase 1 — Vendor migrations 🟡 Primary surface done

| Spec | Implementation |
|---|---|
| `migrate-stm32-extractor` | ✅ CMSIS-SVD + STM32 open-pin-data merged for 503 chips |
| `migrate-rp2040-pico-sdk-extractor` | ✅ Real Pico-SDK SVD reader |
| `migrate-nxp-mcux-extractor` | ✅ Real NXP per-device XML reader |
| `migrate-espressif-esp-idf-extractor` | ✅ All 8 ESP32 families with core fallback |
| `migrate-nordic-zephyr-extractor` | ✅ DTS preprocessing + 159 chips pass |
| `migrate-microchip-dfp-extractor` | ✅ Real ATDF parser (47 chips) |
| `migrate-modm-enrichment-extractor` | ✅ XML enrichment + merge integration |

What remains: **codegen-side `_build_<vendor>_device_ir`
deletion**.  Each callable can be removed once parity is
confirmed for that vendor's admitted devices via the parity
gate.  This is destructive cleanup, deliberately left for
human review.

### Phase 2 — Bulk infrastructure ✅ Archived (3/3)

| Spec | Outcome |
|---|---|
| `add-bulk-discovery-cmsis-pack-manager` | `bulk` CLI + sharding + bulk-report.json |
| `add-cross-source-merge` | merge_payloads + STM32_MERGE_POLICY + schema 1.3.0 |
| `add-coverage-index-and-dashboard` | index.yml + coverage-dashboard.md + CI gate |

### Phase 3 — Coverage expansion (4/4 implementations)

| Spec | Implementation |
|---|---|
| `add-microchip-pic-extractor` | ✅ Reuses ATDF parser, 8 families bound |
| `add-stm32-cubemx-db-extractor` | ⏳ Stub only (CubeMX install not present) |
| `add-msp430-extractor` | ✅ Real header parser, port grouping |
| `add-riscv-community-svd-extractor` | ✅ Archived |

### Phase 4 — Stretch (2/2)

| Spec | Implementation |
|---|---|
| `add-modm-data-pdf-extractor` | ✅ pdfminer.six + holtek template |
| `add-8051-extractor` | ✅ SDCC SFR header parser |

### Bulk-admitted catalog

**4,400+ chips** across 22 vendors / 566+ families in
`alloy-devices-yml/bulk-admitted/`.  Built via:

* CMSIS-Pack catalog (via cmsis-pack-manager): 3,650 chips
  across 16 vendors.
* STM32 cross-source merge (CMSIS-SVD ⊕ open-pin-data):
  503 chips with full pinmux + AF tables.
* Zephyr DTS (cpp-preprocessed): 159 chips across 5 vendor
  families.
* Vendor-direct extractors: 17 admitted + Microchip DFP +
  Espressif + NXP iMXRT.

### Tests

* alloy-data-extractor: **197 tests + 1 skip green**.
* alloy-codegen: parity gate 17/17, full pytest pass.

## Why Phase 1 isn't fully complete autonomously

Each Phase-1 vendor migration is a multi-step refactor:

1. Port the parser from `alloy-codegen/src/alloy_codegen/sources/<vendor>.py`
   into `alloy-data-extractor/src/alloy_data_extractor/extractors/<vendor>.py`. ✅ done autonomously for the primary surface.
2. Layer the deeper enrichment (pinmux, clock tree, IOMUX, dual-core,
   register tree) — currently 🟡 deferred. ⛔ blocked on bigger ports.
3. Re-extract admitted devices through the new parser → write
   fresh YAMLs to alloy-devices-yml.
4. Verify the parity gate stays green for that vendor's devices.
5. Delete the codegen-side parser + matching
   `_build_<vendor>_device_ir` from `stages/normalize.py`.
6. Remove the vendor's tuple(s) from `_KNOWN_DRIFT` in
   `tests/test_yaml_parity_gate.py`.

Steps 3 and 4 require running the codegen pipeline against
**source pins that may need network refresh** (Microchip DFP
SSL-blocked on this workstation, etc).  The parity gate is the
contract that makes the deletion in step 5 safe, and we can't
run it end-to-end offline for every vendor.

The autonomous session shipped Phase 0 plus the **primary
extractor surface** for every admitted vendor.  The remaining
work — pinmux/clock-tree/register-tree enrichment, YAML
re-emission, parity-gated codegen deletion — is per-vendor
daytime work.

## Recommended Phase 1 order

Start with vendors that build offline on the existing source-pin
cache (no fresh downloads needed):

1. **Phase 1.1 — STM32** (`migrate-stm32-extractor`).
   - STM32 IR builds offline (verified during the Phase-0 session).
   - 5 admitted devices, all currently `xpass` in the parity gate
     (no drift) → migration risk is lowest.
   - Removes ~640 LOC from codegen-side `sources/`.
2. **Phase 1.5 — RP2040** (`migrate-rp2040-pico-sdk-extractor`).
   - Currently in `_KNOWN_DRIFT` → migration regenerates the
     YAMLs and removes the entry.
3. **Phase 1.3 — NXP iMXRT** (`migrate-nxp-mcux-extractor`).
   - Same drift situation as RP2040.
4. **Phase 1.4 — Espressif** (`migrate-espressif-esp-idf-extractor`).
5. **Phase 1.6 — Nordic Zephyr** (`migrate-nordic-zephyr-extractor`).
   - Needs `ALLOY_CODEGEN_SOURCE_ZEPHYR_DTS_ROOT` set — currently
     skipped by the parity gate on this machine.
6. **Phase 1.2 — Microchip DFP** (`migrate-microchip-dfp-extractor`).
   - Largest single file (1,053 LOC).  Needs a populated
     Microchip pack cache (currently SSL-blocked on this
     workstation; works on machines with proper certs).
7. **Phase 1.7 — modm enrichment** (`migrate-modm-enrichment-extractor`).
   - Last because it's a secondary extractor; depends on
     `add-cross-source-merge` (Phase 2.2) for full integration,
     but can land as transitional plumbing earlier.

## Per-migration recipe

For each Phase-1 vendor, the recipe is:

```
# 1. Create the new extractor module (data-extractor)
cp alloy-codegen/src/alloy_codegen/sources/<v>.py \
   alloy-data-extractor/src/alloy_data_extractor/extractors/<v>.py
# Strip alloy_codegen.* imports; replace Raw* types with extractor's.

# 2. Wrap in the Extractor protocol class
# (see alloy-data-extractor/src/.../extractors/cmsis_svd.py for the
# pattern — small adapter class at the bottom of the module
# decorated with @register_extractor(...).)

# 3. Re-extract admitted devices
alloy-data-extract --vendor <v> --family <f> \
  --device <d1> --device <d2> \
  --source <key>=<path> ...

# 4. Verify parity stays green
cd alloy-codegen
python -m pytest tests/test_yaml_parity_gate.py -k <v> -v

# 5. Delete codegen-side parser + _build_<v>_device_ir
# 6. Remove (vendor, family, device) entries from _KNOWN_DRIFT
# 7. Run full pytest in both repos before commit.
```

## Open OpenSpecs

These 16 OpenSpec proposals are scaffolded under
`openspec/changes/` and pass `openspec validate --strict`.  They
are ready to implement in roughly the order listed:

```
migrate-stm32-extractor
migrate-rp2040-pico-sdk-extractor
migrate-nxp-mcux-extractor
migrate-espressif-esp-idf-extractor
migrate-nordic-zephyr-extractor
migrate-microchip-dfp-extractor
migrate-modm-enrichment-extractor

add-bulk-discovery-cmsis-pack-manager
add-cross-source-merge
add-coverage-index-and-dashboard

add-microchip-pic-extractor
add-stm32-cubemx-db-extractor
add-msp430-extractor
add-riscv-community-svd-extractor

add-modm-data-pdf-extractor
add-8051-extractor
```

See `ROADMAP.md` for the full plan with phase boundaries +
estimated timelines.
