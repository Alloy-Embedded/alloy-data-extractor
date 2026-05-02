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


# Originally-admitted ST chips — kept for back-compat / quick re-emit.
# `--family stm32g0 --discover` adds every package variant the
# STM32_open_pin_data ships, so this list isn't authoritative.
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
# Auto-discover every package variant a family ships
# ---------------------------------------------------------------------------


_FAMILY_TO_SVD_PREFIXES: dict[str, tuple[str, ...]] = {
    "stm32f0": (
        "STM32F030", "STM32F031", "STM32F038", "STM32F042",
        "STM32F048", "STM32F051", "STM32F058", "STM32F070",
        "STM32F071", "STM32F072", "STM32F078", "STM32F091",
        "STM32F098",
    ),
    "stm32f1": (
        "STM32F100", "STM32F101", "STM32F102", "STM32F103",
        "STM32F105", "STM32F107",
    ),
    "stm32f3": (
        "STM32F301", "STM32F302", "STM32F303", "STM32F318",
        "STM32F328", "STM32F334", "STM32F358", "STM32F373",
        "STM32F378", "STM32F398",
    ),
    "stm32f4": (
        "STM32F401", "STM32F405", "STM32F407", "STM32F410",
        "STM32F411", "STM32F412", "STM32F413", "STM32F415",
        "STM32F417", "STM32F423", "STM32F427", "STM32F429",
        "STM32F437", "STM32F439", "STM32F446", "STM32F469",
        "STM32F479",
    ),
    "stm32g0": (
        "STM32G030", "STM32G031", "STM32G041",
        "STM32G050", "STM32G051", "STM32G061",
        "STM32G070", "STM32G071", "STM32G081",
        "STM32G0B0", "STM32G0B1", "STM32G0C1",
    ),
    "stm32g4": (
        "STM32G431", "STM32G441", "STM32G471", "STM32G473",
        "STM32G474", "STM32G483", "STM32G484", "STM32G491",
        "STM32G4A1",
    ),
    "stm32h7": (
        "STM32H723", "STM32H725", "STM32H730", "STM32H733",
        "STM32H735", "STM32H742", "STM32H743", "STM32H745",
        "STM32H747", "STM32H750", "STM32H753", "STM32H755",
        "STM32H757", "STM32H7A3", "STM32H7B0", "STM32H7B3",
    ),
}


def _device_id_from_xml(xml_name: str) -> str:
    """Pick the canonical device id from an open-pin-data XML name.

    Strategy: take the FIRST ordercode within parenthesised ranges
    so ``STM32G030C(6-8)Tx.xml`` → ``stm32g030c6tx``; non-paren
    names just lose the ``.xml`` suffix.
    """
    stem = xml_name.rsplit(".", 1)[0]
    if "(" in stem and ")" in stem:
        # Take the first option inside the first paren group.
        prefix, rest = stem.split("(", 1)
        opts, suffix = rest.split(")", 1)
        first = opts.split("-", 1)[0]
        stem = f"{prefix}{first}{suffix}"
    return stem.lower()


def _resolve_svd_for_xml(xml_name: str, family: str) -> str | None:
    """Find the SVD basename whose prefix matches the open-pin-data XML."""
    upper = xml_name.upper()
    for prefix in _FAMILY_TO_SVD_PREFIXES.get(family, ()):
        if upper.startswith(prefix):
            return f"{prefix}.svd"
    return None


def _discover_family_chips(
    family: str, open_pin_dir: Path,
) -> tuple[_ChipSources, ...]:
    """Return one _ChipSources per open-pin-data XML in ``family``."""
    out: list[_ChipSources] = []
    for prefix in _FAMILY_TO_SVD_PREFIXES.get(family, ()):
        for xml in sorted(open_pin_dir.glob(f"{prefix}*.xml")):
            name = xml.name
            device = _device_id_from_xml(name)
            svd = _resolve_svd_for_xml(name, family)
            if svd is None:
                continue
            out.append(_ChipSources(
                family=family, device=device,
                svd=svd, open_pin_xml=name, cubemx_chip=name,
            ))
    return tuple(out)


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
    parser.add_argument("--family", default=None,
                        help="When set with --discover, bulk-emit every "
                             "open-pin-data XML for the family (stm32g0 / "
                             "stm32f4 / …).")
    parser.add_argument("--discover", action="store_true",
                        help="Discover all package variants under "
                             "--family from open-pin-data instead of using "
                             "the admitted hand-curated list.")
    args = parser.parse_args(argv)

    if args.discover:
        if not args.family:
            print("ERROR: --discover requires --family", file=sys.stderr)
            return 2
        matches = _discover_family_chips(args.family, args.open_pin_data_dir)
        if not matches:
            print(f"ERROR: no open-pin-data XMLs found for family "
                  f"{args.family!r} under {args.open_pin_data_dir}",
                  file=sys.stderr)
            return 1
    else:
        matches = _ADMITTED_STM32
    if args.chip:
        matches = tuple(c for c in matches if c.device == args.chip)
        if not matches:
            print(f"ERROR: chip {args.chip!r} not in match set.", file=sys.stderr)
            return 2

    cubemx_db = args.cubemx_db if args.cubemx_db.is_dir() else None
    if cubemx_db is None:
        print(f"NOTE: CubeMX DB not found at {args.cubemx_db}.  "
              "Skipping cubemx enrichment.", file=sys.stderr)

    failures = 0
    skipped_no_svd = 0
    print(f"Re-emitting {len(matches)} chip(s) into {args.out}")
    print()
    for chip in matches:
        # Pre-flight: skip silently when the SVD isn't shipped with
        # this cmsis-svd-data version (F415/F417/F423/F437/F439/F479
        # land in newer packs).  Better than failing every variant.
        svd_path = args.svd_dir / chip.svd
        if not svd_path.is_file():
            skipped_no_svd += 1
            continue
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
            print(f"  ✓ {chip.device:18s} → {out_path.relative_to(args.out)} "
                  f"({size:>7,}B)")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ {chip.device}: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print()
    emitted = len(matches) - failures - skipped_no_svd
    print(f"{emitted}/{len(matches)} chips re-emitted; "
          f"{skipped_no_svd} skipped (SVD missing); {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
