# alloy-data-extractor

Multi-vendor ETL pipeline that produces canonical device YAML
files for the [alloy-devices-yml](https://github.com/Alloy-Embedded/alloy-devices-yml)
data repository.

```
[vendor packs]
   │ pulled by extractors
   ▼
alloy-data-extractor   ← you are here  (Python ETL)
   │ writes YAML
   ▼
alloy-devices-yml         (data only, schema-validated)
   │ consumed by
   ▼
alloy-codegen           (C++ generator)
alloy-codegen-rust      (future siblings)
alloy-codegen-zig
```

## Coverage targets

| Architecture | Vendor                          | Source                                | Status   |
| ------------ | ------------------------------- | ------------------------------------- | -------- |
| Cortex-M     | ST, NXP, Microchip, Nordic, Renesas, TI, Infineon, Ambiq, SiLabs, GD, Nuvoton, … | CMSIS-SVD + CMSIS-Pack + Zephyr DTS  | partial  |
| AVR 8-bit    | Microchip                       | ATDF (Atmel Pack)                     | partial  |
| **PIC**      | Microchip                       | MPLAB X DFP                           | planned  |
| PIC24/dsPIC  | Microchip                       | MPLAB X DFP                           | planned  |
| PIC32        | Microchip                       | MPLAB X DFP                           | planned  |
| RISC-V       | ESP32-C, GD32V, BL602, CH32V, … | Vendor SDKs + community SVD           | partial  |
| Xtensa       | Espressif                       | ESP-IDF SOC headers                   | partial  |
| MSP430       | TI                              | TI SysConfig                          | planned  |
| 8051         | Nuvoton, SiLabs, STC            | Vendor SDKs                           | planned  |

The "partial" extractors exist as alloy-codegen sibling code
today (in `alloy-codegen/src/alloy_codegen/sources/`) and will
be moved here in incremental migration changes.

## Quick start

```bash
pip install -e .

# Run a single extractor against a pinned source root
alloy-data-extract --vendor st --family stm32g0 \
    --output-root ../alloy-devices-yml \
    --source cmsis-svd-data=/path/to/cmsis-svd-data
```

The CLI walks every device the catalog admits for the requested
scope, runs the appropriate extractor + normalizer, and writes
schema-validated YAML files into the configured output root.

## Architecture

```
src/alloy_data_extractor/
    extractors/       # one module per vendor source
        cmsis_svd.py
        atdf.py       # AVR + SAM + PIC via MPLAB X DFP
        mcuxpresso.py
        zephyr_dts.py
        esp_idf.py
        modm_data.py
        pico_sdk.py
    normalize/        # vendor-specific IR builders
    emit/             # canonical YAML writer (uses alloy-codegen's schema)
    cli.py            # alloy-data-extract entry point
data/
    source_pins.toml  # pinned upstream SHAs / pack versions
```

## Source pinning

`data/source_pins.toml` records the exact upstream revision each
extractor consumes (cmsis-svd-data SHA, Microchip MPLAB DFP
version, Zephyr SHA, etc.).  Bumping a pin is a reviewable PR.
CI re-runs all extractors against the new pin and opens a PR
against alloy-devices-yml when YAML output drifts.

## License

MIT — same as alloy-codegen and alloy-devices-yml.

## Status

This repo just landed.  The first proof-of-life extractor is
CMSIS-SVD (covers ST, plus any other vendor with a community
SVD).  The other extractors (ATDF, MCUXpresso, Zephyr DTS,
ESP-IDF, modm-data, Pico SDK) are migrated incrementally from
alloy-codegen — tracked under per-vendor migration changes in
the alloy-codegen OpenSpec queue.
