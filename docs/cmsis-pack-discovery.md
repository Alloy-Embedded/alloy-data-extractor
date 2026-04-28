# CMSIS-Pack discovery

The `cmsis-pack` extractor (`src/alloy_data_extractor/extractors/cmsis_pack.py`)
is the bulk-discovery backbone for ARM-targeted chips.  It wraps
[`cmsis-pack-manager`](https://github.com/pyocd/cmsis-pack-manager) to:

1. Walk the global CMSIS-Pack catalog (~11,500 chips across 50+ vendors).
2. Download each chip's `.pack` file (a ZIP archive) on demand.
3. Extract the SVD from the pack and run the existing CMSIS-SVD reader.
4. Stamp catalog metadata onto the result (canonical core, memories,
   pack provenance).

## Coverage by vendor (catalog totals)

| Vendor | Chips |
|---|---|
| ST | 2,630 |
| NXP | 1,534 |
| SiLabs | 1,258 |
| Nuvoton | 1,058 |
| Infineon | 1,007 |
| Cypress | 938 |
| Holtek | 485 |
| Microchip | 485 |
| TI | 398 |
| GigaDevice | 373 |
| Renesas | 118 |
| Ambiq | small (<20) |
| Toshiba, Puya, Sonix, FMD, Geehy, Sinowealth, ARM, Abov, … | 50 vendors total |

## Smoke-test pass rate

A 1-chip-per-vendor smoke test against the top 23 vendors was 17/23 PASS:

* PASS (real SVD admitted): silabs, nuvoton, infineon, cypress, ti,
  nsing, toshiba, renesas, puya, sonix, fmd, geehy, arm, sinowealth,
  abov, ambiq, analog devices.
* FAIL (vendor-specific upstream issues):
  - nxp: pack contains no SVD file.
  - holtek: pack contains no SVD file.
  - hdsc: pack contains no SVD file.
  - cmsemicon: pack ships a non-XML payload that pdsc parser rejects.
  - gigadevice / mindmotion: pack download failed (URL or auth issue).

## Usage

### Single chip

```python
from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest, resolve_extractor_by_id,
)
import alloy_data_extractor.pipeline  # registers extractors

ext = resolve_extractor_by_id("cmsis-pack")
result = ext.extract(ExtractionRequest(
    vendor="st",          # alloy-canonical short name
    family="stm32g0",     # informational; cmsis-pack derives from sub_family
    device="STM32G071C8Tx",
    source_paths={},      # not needed — pack auto-downloads
    revision="cmsis-pack:catalog",
))
print(result.payload["identity"]["core"])  # "cortex-m0plus"
```

### Bulk fan-out across vendors

```python
from alloy_data_extractor.extractors.cmsis_pack import (
    load_catalog, enumerate_catalog_chips,
)
cache = load_catalog()
for chip in enumerate_catalog_chips(cache, vendor_substring="silabs"):
    print(chip.name, chip.core)  # 1,258 SiLabs chips
```

## Cache location

Packs live under `cmsis-pack-manager`'s default cache:

* macOS: `~/Library/Application Support/cmsis-pack-manager/`
* Linux: `~/.cache/cmsis-pack-manager/`

Initial run downloads the vendor index (vidx, ~5MB) and per-vendor
pack files (~100MB-500MB each).  Subsequent runs re-use the local
copy and only need network when a chip's pack is missing or when
``load_catalog(refresh=True)`` is called.

## What this gives you over a raw SVD parse

* **Identity correction**: STM32G0 SVDs name themselves "CM0", but the
  CMSIS-Pack catalog correctly says CortexM0Plus.  The extractor
  takes the catalog value over the SVD value when both are present.
* **Memories**: catalog `memories` block carries flash + sram
  base/size/access — SVDs don't.
* **Provenance**: every YAML records `pack_vendor` / `pack_name` /
  `pack_version` so reviewers can audit which CMSIS-Pack version
  produced each chip.

## Limitations

* Some vendor packs ship without SVDs at all — the extractor surfaces
  a clear `ValueError` and the bulk pipeline records `EXTRACT_FAILED`.
* Register tree depth depends on the upstream pack; some vendors ship
  abbreviated SVDs.
* The catalog is only as fresh as the last `load_catalog(refresh=True)`
  invocation — there's no auto-refresh.
