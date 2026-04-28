# Phase 1 Handoff Notes

This document captures where the autonomous Phase-0 implementation
session stopped and what the next session needs to know to start
Phase 1 (vendor migrations) safely.

## What's already done (commit history)

Phase 0 — Foundation, archived:

| Spec | Repos touched | Status |
|---|---|---|
| `lock-canonical-yaml-schema-v1` | extractor + codegen + alloy-devices-yml | ✅ Archived |
| `define-extractor-protocol` | extractor only | ✅ Archived |
| `add-codegen-yaml-parity-gate` | codegen only | ✅ Archived |

Phase 1 — Vendor migrations, partial autonomous progress:

| Spec | Status | Implementation |
|---|---|---|
| `migrate-stm32-extractor` | 🟡 partial | Real CMSIS-SVD-backed extractor for stm32f4/stm32g0; pinmux/AF still on legacy path |
| `migrate-rp2040-pico-sdk-extractor` | 🟡 partial | Real Pico-SDK SVD reader; clock-tree + bring-up descriptors deferred |
| `migrate-nxp-mcux-extractor` | 🟡 partial | Real NXP per-device XML reader; IOMUX/GPIO pin tables deferred |
| `migrate-espressif-esp-idf-extractor` | 🟡 partial | Real esp-idf SVD reader; dual-core control plane + DPORT patches deferred |
| `migrate-nordic-zephyr-extractor` | 🟡 partial | DTS extractor already shipping; pinctrl decoder migration pending |
| `migrate-microchip-dfp-extractor` | 🟡 partial | Real ATDF parser (peripherals + interrupts); register-tree port deferred |
| `migrate-modm-enrichment-extractor` | ⛔ blocked | Stub only — depends on Phase 2.2 cross-source merge |

"Partial" = primary canonical-IR fields (peripherals, interrupts,
core, basic identity) extract correctly; deeper enrichment
(pinmux, clock tree, register tree, factory calibration, etc.)
still flows from the codegen legacy `_build_<vendor>_device_ir`
path.

Tests added (all green on this offline workstation):

* alloy-data-extractor: 71 tests green + 1 skip.
* alloy-codegen: parity gate is 11 pass + 4 xfail + 2 skip on the
  17 admitted devices.

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
