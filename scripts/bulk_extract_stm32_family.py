"""Bulk-extract every chip in an STM32 sub-family from CMSIS-SVD.

Usage::

    PYTHONPATH=src:../alloy-codegen/src \
        python3 scripts/bulk_extract_stm32_family.py \
            --svd-dir <cmsis-svd-data>/data/STMicro \
            --family stm32g0 \
            --pattern 'STM32G0*.svd' \
            --out /path/to/alloy-devices-yml

Each ``STM32xxxYz.svd`` becomes one canonical YAML at
``vendors/st/<family>/devices/<svd_basename_lowercased>.yml``.

This script does NOT enrich pinout / package data — that comes from
the secondary stm32-open-pin-data + stm32-cubemx extractors (TBD).
The output here is the SVD-only skeleton: complete register map,
correct IRQs, placeholder memory + pinout (1 row each, flagged as
``role: extractor-placeholder``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# alloy-codegen sibling clone — needed for the v2.1 reader.
_CODEGEN_SRC = ROOT.parent / "alloy-codegen" / "src"
if _CODEGEN_SRC.is_dir() and str(_CODEGEN_SRC) not in sys.path:
    sys.path.insert(0, str(_CODEGEN_SRC))

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml  # noqa: E402
from alloy_data_extractor.extractors.cmsis_svd_v2_1 import (  # noqa: E402
    extract_device,
)


def _device_id_from_svd(svd_path: Path) -> str:
    """Lowercase basename, no extension — ``STM32G031.svd`` →
    ``stm32g031``."""
    return svd_path.stem.lower()


def _extract_one(svd: Path, vendor: str, family: str, output_root: Path) -> tuple[Path, int, int]:
    device_id = _device_id_from_svd(svd)
    payload = extract_device(
        vendor=vendor,
        family=family,
        device=device_id,
        svd_path=svd,
    )
    out_path = write_device_yaml(
        payload=payload,
        output_root=output_root,
        vendor=vendor,
        family=family,
        device=device_id,
    )
    return out_path, len(payload.get("peripherals", [])), len(payload.get("templates", {}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svd-dir", type=Path, required=True,
                        help="Directory containing STM32 SVD files.")
    parser.add_argument("--vendor", default="st",
                        help="Vendor namespace (default: st).")
    parser.add_argument("--family", required=True,
                        help="Family slug, e.g. stm32g0.")
    parser.add_argument("--pattern", required=True,
                        help="Glob pattern within --svd-dir, e.g. 'STM32G0*.svd'.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Path to alloy-devices-yml repo root.")
    args = parser.parse_args(argv)

    if not args.svd_dir.is_dir():
        print(f"ERROR: SVD dir not found: {args.svd_dir}", file=sys.stderr)
        return 2

    matches = sorted(args.svd_dir.glob(args.pattern))
    if not matches:
        print(f"ERROR: no SVDs match {args.pattern} under {args.svd_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(matches)} SVD file(s) for {args.vendor}/{args.family}.")
    print()

    failures = 0
    total_bytes = 0
    for svd in matches:
        try:
            out_path, n_per, n_tmpl = _extract_one(
                svd=svd, vendor=args.vendor, family=args.family, output_root=args.out,
            )
            size = out_path.stat().st_size
            total_bytes += size
            print(
                f"  ✓ {svd.name:25s} → {out_path.relative_to(args.out)} "
                f"({size:>7,}B, {n_per:>3} peripherals, {n_tmpl:>3} templates)"
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ {svd.name:25s}: {type(exc).__name__}: {exc}")

    print()
    print(f"{len(matches) - failures}/{len(matches)} chips extracted, "
          f"{total_bytes / 1024:.1f} KB total")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
