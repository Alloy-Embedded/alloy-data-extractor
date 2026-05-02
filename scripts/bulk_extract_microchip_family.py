"""Bulk-extract every chip in a Microchip family from ATDF files.

Usage::

    python3 scripts/bulk_extract_microchip_family.py \\
        --atdf-dir <microchip-dfp>/<family-pack>/atdf \\
        --family avr-da \\
        --pattern 'AVR*DA*.atdf' \\
        --out /path/to/alloy-devices-yml

Each ``ATmega328P.atdf`` / ``AVR128DA32.atdf`` becomes one canonical
YAML at ``vendors/microchip/<family>/devices/<atdf_basename>.yml``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_CODEGEN_SRC = ROOT.parent / "alloy-codegen" / "src"
if _CODEGEN_SRC.is_dir() and str(_CODEGEN_SRC) not in sys.path:
    sys.path.insert(0, str(_CODEGEN_SRC))

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml  # noqa: E402
from alloy_data_extractor.extractors.microchip_atdf_v2_1 import (  # noqa: E402
    extract_device,
)


def _device_id_from_atdf(atdf_path: Path) -> str:
    return atdf_path.stem.lower()


def _extract_one(
    atdf: Path, vendor: str, family: str, output_root: Path,
) -> tuple[Path, int, int]:
    device_id = _device_id_from_atdf(atdf)
    payload = extract_device(
        vendor=vendor, family=family, device=device_id, atdf_path=atdf,
    )
    out_path = write_device_yaml(
        payload=payload, output_root=output_root,
        vendor=vendor, family=family, device=device_id,
    )
    return out_path, len(payload.get("peripherals", [])), len(payload.get("templates", {}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atdf-dir", type=Path, required=True)
    parser.add_argument("--vendor", default="microchip")
    parser.add_argument("--family", required=True)
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.atdf_dir.is_dir():
        print(f"ERROR: ATDF dir not found: {args.atdf_dir}", file=sys.stderr)
        return 2

    matches = sorted(args.atdf_dir.glob(args.pattern))
    if not matches:
        print(f"ERROR: no ATDFs match {args.pattern} under {args.atdf_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(matches)} ATDF file(s) for {args.vendor}/{args.family}.")
    print()

    failures = 0
    total_bytes = 0
    for atdf in matches:
        try:
            out_path, n_per, n_tmpl = _extract_one(
                atdf=atdf, vendor=args.vendor, family=args.family, output_root=args.out,
            )
            size = out_path.stat().st_size
            total_bytes += size
            print(
                f"  ✓ {atdf.name:25s} → {out_path.relative_to(args.out)} "
                f"({size:>7,}B, {n_per:>3} peripherals, {n_tmpl:>3} templates)"
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ {atdf.name:25s}: {type(exc).__name__}: {exc}")

    print()
    print(f"{len(matches) - failures}/{len(matches)} chips extracted, "
          f"{total_bytes / 1024:.1f} KB total")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
