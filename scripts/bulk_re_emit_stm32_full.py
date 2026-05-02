"""Re-emit every admitted STM32 chip with the full v2.1 enrichment stack.

Composes five extractors per chip:

  1. cmsis_svd_v2_1            (primary — registers + IRQs)
  2. stm32_open_pin_data_v2_1  (pinout, ip_version, pin_options)
  3. stm32_overlay_v2_1        (memory, profiles, ADC calibration)
  4. stm32_tier_v2_1           (timer trigger_sources, master_outputs,
                                 PWM break/deadtime, ADC external_triggers,
                                 USART/SPI/I²C/ADC option encodings)
  5. stm32_cubemx_v2_1         (clock topology + select_register encoding,
                                 DMA matrix, ip_version)

Result is merged through ``STM32_MERGE_POLICY`` and written to the
``alloy-devices-yml`` repo via ``write_device_yaml``.

Usage::

    python3 scripts/bulk_re_emit_stm32_full.py \\
        --out /path/to/alloy-devices-yml

Optional knobs:

* ``--cubemx-db PATH`` — override the CubeMX DB root (defaults to
  the macOS .app bundle).
* ``--svd-dir PATH``   — override the cmsis-svd-data root.
* ``--open-pin-data-dir PATH`` — override the STM32_open_pin_data
  ``mcu/`` root.
* ``--chip <chip>``    — limit to a single admitted device.

The chip → source-file map below is hand-curated (5 admitted ST
chips today; one row per chip).  Adding a new admitted device =
add one row.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_CODEGEN_SRC = ROOT.parent / "alloy-codegen" / "src"
if _CODEGEN_SRC.is_dir() and str(_CODEGEN_SRC) not in sys.path:
    sys.path.insert(0, str(_CODEGEN_SRC))

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml  # noqa: E402
from alloy_data_extractor.extractors.cmsis_svd_v2_1 import (  # noqa: E402
    extract_device as svd_extract,
)
from alloy_data_extractor.extractors.stm32_cubemx_v2_1 import (  # noqa: E402
    extract_device as cubemx_extract,
)
from alloy_data_extractor.extractors.stm32_open_pin_data_v2_1 import (  # noqa: E402
    extract_device as opd_extract,
)
from alloy_data_extractor.extractors.stm32_overlay_v2_1 import (  # noqa: E402
    extract_device as overlay_extract,
)
from alloy_data_extractor.extractors.stm32_tier_v2_1 import (  # noqa: E402
    extract_device as tier_extract,
)
from alloy_data_extractor.merge_v2_1 import (  # noqa: E402
    STM32_MERGE_POLICY,
    merge_payloads,
)


# ---------------------------------------------------------------------------
# Chip → source-file map.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ChipSources:
    family:        str             # alloy-devices-yml family slug
    device:        str             # alloy-devices-yml device slug
    svd:           str             # SVD basename inside cmsis-svd-data/data/STMicro
    open_pin_xml:  str             # XML basename inside STM32_open_pin_data/mcu
    cubemx_chip:   str             # XML basename inside <cubemx-db>/mcu


# Hand-curated for the five admitted ST chips.  The CubeMX names
# pick the chip's exact ordercode + package; the open-pin-data XML
# usually covers a handful of variants behind the parenthesised
# letters in the filename.
_ADMITTED_STM32: tuple[_ChipSources, ...] = (
    _ChipSources(family="stm32g0", device="stm32g030f6",
                 svd="STM32G030.svd",
                 open_pin_xml="STM32G030F6Px.xml",
                 cubemx_chip="STM32G030F6Px.xml"),
    _ChipSources(family="stm32g0", device="stm32g071rb",
                 svd="STM32G071.svd",
                 open_pin_xml="STM32G071RBIx.xml",
                 cubemx_chip="STM32G071R(6-8-B)Tx.xml"),
    _ChipSources(family="stm32g0", device="stm32g0b1re",
                 svd="STM32G0B1.svd",
                 open_pin_xml="STM32G0B1R(B-C-E)Tx.xml",
                 cubemx_chip="STM32G0B1R(B-C-E)Tx.xml"),
    _ChipSources(family="stm32f4", device="stm32f401re",
                 svd="STM32F401.svd",
                 open_pin_xml="STM32F401R(D-E)Tx.xml",
                 cubemx_chip="STM32F401R(D-E)Tx.xml"),
    _ChipSources(family="stm32f4", device="stm32f405rg",
                 svd="STM32F405.svd",
                 open_pin_xml="STM32F405RGTx.xml",
                 cubemx_chip="STM32F405RGTx.xml"),
)


# ---------------------------------------------------------------------------
# Defaults — sensible on this dev machine
# ---------------------------------------------------------------------------


_DEFAULT_SVD_DIR = (
    ROOT.parent / "alloy-codegen" / ".cache" / "sources"
    / "cmsis-svd-data" / "data" / "STMicro"
)
_DEFAULT_OPEN_PIN_DIR = (
    ROOT.parent / "alloy-codegen" / ".cache" / "sources"
    / "STM32_open_pin_data" / "mcu"
)
_DEFAULT_CUBEMX_DB = Path(
    "/Applications/STMicroelectronics/STM32CubeMX.app/"
    "Contents/Resources/db"
)
_DEFAULT_OVERLAY_ROOT = ROOT / "data"


# ---------------------------------------------------------------------------
# One-chip pipeline
# ---------------------------------------------------------------------------


def _re_emit_one(
    *,
    chip: _ChipSources,
    svd_dir: Path,
    open_pin_dir: Path,
    overlay_root: Path,
    cubemx_db: Path | None,
    output_root: Path,
) -> tuple[Path, dict[str, str]]:
    """Run all 5 extractors for one chip, merge, write to disk.

    Returns ``(out_path, sources_used)``.  ``sources_used`` lists
    which extractors contributed (skipping ones whose source files
    are missing).
    """
    sources_used: dict[str, str] = {}

    svd_path = svd_dir / chip.svd
    if not svd_path.is_file():
        raise FileNotFoundError(f"SVD missing: {svd_path}")
    primary = svd_extract(
        vendor="st", family=chip.family, device=chip.device, svd_path=svd_path,
    )
    sources_used["cmsis-svd"] = chip.svd

    enrichments: list[dict] = []

    # open-pin-data
    opd_path = open_pin_dir / chip.open_pin_xml
    if opd_path.is_file():
        enrichments.append(opd_extract(
            vendor="st", family=chip.family,
            device=chip.device, xml_path=opd_path,
        ))
        sources_used["stm32-open-pin-data"] = chip.open_pin_xml

    # overlay
    family_toml = overlay_root / "vendors" / "st" / chip.family / "family.toml"
    if family_toml.is_file():
        enrichments.append(overlay_extract(
            vendor="st", family=chip.family,
            device=chip.device, overlay_root=overlay_root,
        ))
        sources_used["stm32-overlay"] = f"{chip.family}/family.toml"

    # tier (re-uses the open-pin-data XML)
    if opd_path.is_file():
        enrichments.append(tier_extract(
            vendor="st", family=chip.family,
            device=chip.device, open_pin_data_xml=opd_path,
        ))
        sources_used["stm32-tier"] = chip.open_pin_xml

    # cubemx
    if cubemx_db is not None and cubemx_db.is_dir():
        cubemx_chip_xml = cubemx_db / "mcu" / chip.cubemx_chip
        if cubemx_chip_xml.is_file():
            enrichments.append(cubemx_extract(
                vendor="st", family=chip.family,
                device=chip.device, db_root=cubemx_db,
                chip_xml=cubemx_chip_xml,
            ))
            sources_used["stm32-cubemx"] = chip.cubemx_chip

    result = merge_payloads(
        primary=primary, enrichments=tuple(enrichments),
        policy=STM32_MERGE_POLICY,
    )
    out_path = write_device_yaml(
        payload=result.payload, output_root=output_root,
        vendor="st", family=chip.family, device=chip.device,
    )
    return out_path, sources_used


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="alloy-devices-yml repo root")
    parser.add_argument("--svd-dir", type=Path, default=_DEFAULT_SVD_DIR)
    parser.add_argument("--open-pin-data-dir", type=Path,
                        default=_DEFAULT_OPEN_PIN_DIR)
    parser.add_argument("--overlay-root", type=Path, default=_DEFAULT_OVERLAY_ROOT)
    parser.add_argument("--cubemx-db", type=Path, default=_DEFAULT_CUBEMX_DB)
    parser.add_argument("--chip", default=None,
                        help="Limit run to a single admitted device.")
    args = parser.parse_args(argv)

    matches = _ADMITTED_STM32
    if args.chip:
        matches = tuple(c for c in matches if c.device == args.chip)
        if not matches:
            print(f"ERROR: chip {args.chip!r} not in admitted set.", file=sys.stderr)
            print("Admitted: " + ", ".join(c.device for c in _ADMITTED_STM32),
                  file=sys.stderr)
            return 2

    cubemx_db = args.cubemx_db if args.cubemx_db.is_dir() else None
    if cubemx_db is None:
        print(f"NOTE: CubeMX DB not found at {args.cubemx_db}.  "
              "Skipping cubemx enrichment.", file=sys.stderr)

    failures = 0
    print(f"Re-emitting {len(matches)} chip(s) into {args.out}")
    print()
    for chip in matches:
        try:
            out_path, sources = _re_emit_one(
                chip=chip,
                svd_dir=args.svd_dir,
                open_pin_dir=args.open_pin_data_dir,
                overlay_root=args.overlay_root,
                cubemx_db=cubemx_db,
                output_root=args.out,
            )
            size = out_path.stat().st_size
            sources_str = " + ".join(sources)
            print(f"  ✓ {chip.device:14s} → {out_path.relative_to(args.out)} "
                  f"({size:>7,}B)")
            print(f"    sources: {sources_str}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ {chip.device}: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print()
    print(f"{len(matches) - failures}/{len(matches)} chips re-emitted.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
