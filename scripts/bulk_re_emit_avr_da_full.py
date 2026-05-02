"""Re-emit every admitted AVR-DA chip with the microchip 2-source stack.

Composes:

  1. microchip_atdf_v2_1     (primary — registers + IRQs + per-package pinout)
  2. microchip_overlay_v2_1  (memory + clock profiles + max_clocks)

Result is merged through ``MICROCHIP_MERGE_POLICY`` and written to
``alloy-devices-yml`` via ``write_device_yaml``.

Usage::

    python3 scripts/bulk_re_emit_avr_da_full.py \\
        --atdf-dir <microchip-dfp>/avr-da/atdf \\
        --pattern 'AVR*DA*.atdf' \\
        --out /path/to/alloy-devices-yml
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
    extract_device as atdf_extract,
)
from alloy_data_extractor.extractors.microchip_overlay_v2_1 import (  # noqa: E402
    extract_device as overlay_extract,
)
from alloy_data_extractor.merge_v2_1 import (  # noqa: E402
    MICROCHIP_MERGE_POLICY,
    merge_payloads,
)


def _device_id_from_atdf(path: Path) -> str:
    return path.stem.lower()


def _re_emit_one(
    *,
    atdf_path: Path,
    family: str,
    overlay_root: Path,
    output_root: Path,
) -> tuple[Path, list[str]]:
    device = _device_id_from_atdf(atdf_path)
    primary = atdf_extract(
        vendor="microchip", family=family, device=device, atdf_path=atdf_path,
    )
    sources = ["microchip-atdf"]
    enrichments = []
    family_toml = overlay_root / "vendors" / "microchip" / family / "family.toml"
    if family_toml.is_file():
        enrichments.append(overlay_extract(
            vendor="microchip", family=family, device=device,
            overlay_root=overlay_root,
        ))
        sources.append("microchip-overlay")
    result = merge_payloads(
        primary=primary, enrichments=tuple(enrichments),
        policy=MICROCHIP_MERGE_POLICY,
    )
    out_path = write_device_yaml(
        payload=result.payload, output_root=output_root,
        vendor="microchip", family=family, device=device,
    )
    return out_path, sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atdf-dir", type=Path, required=True)
    parser.add_argument("--family", default="avr-da")
    parser.add_argument("--pattern", default="AVR*DA*.atdf")
    parser.add_argument("--overlay-root", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    matches = sorted(args.atdf_dir.glob(args.pattern))
    if not matches:
        print(f"ERROR: no ATDF matches {args.pattern} under {args.atdf_dir}",
              file=sys.stderr)
        return 1
    print(f"Re-emitting {len(matches)} AVR-DA chip(s) into {args.out}")
    print()

    failures = 0
    for atdf in matches:
        try:
            out_path, sources = _re_emit_one(
                atdf_path=atdf, family=args.family,
                overlay_root=args.overlay_root, output_root=args.out,
            )
            size = out_path.stat().st_size
            print(f"  ✓ {atdf.stem.lower():14s} → {out_path.relative_to(args.out)} "
                  f"({size:>7,}B, sources: {' + '.join(sources)})")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ {atdf.name}: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print()
    print(f"{len(matches) - failures}/{len(matches)} chips re-emitted")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
