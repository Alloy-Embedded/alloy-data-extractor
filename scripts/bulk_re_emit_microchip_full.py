"""Re-emit every admitted Microchip chip with the 3-source stack.

Composes:

  1. microchip_atdf_v2_1     (primary — registers + IRQs + per-package
                              pinout + pin_options + ip_version +
                              description from ATDF <modules>)
  2. microchip_overlay_v2_1  (memory + max_clocks + clock profiles
                              + I²C speed_options from family.toml)
  3. microchip_csp_v2_1      (clock.domains[].select_register +
                              prescaler_register with encoding
                              auto-derived from MPLAB Harmony's
                              clk.py + ATDF <value-group>s — fully
                              auto, no hand-curated encoding tables)

Result is merged through ``MICROCHIP_MERGE_POLICY`` and written to
``alloy-devices-yml`` via ``write_device_yaml``.

Usage::

    python3 scripts/bulk_re_emit_microchip_full.py \\
        --atdf-dir <microchip-dfp>/<pack>/atdf \\
        --pattern 'ATSAME70*.atdf' \\
        --family same70 \\
        --csp-root <microchip-csp> \\
        --out /path/to/alloy-devices-yml

The ``--csp-root`` flag is optional; the run still proceeds with
the 2-source stack when CSP is missing or the family has no
``clk_<X>`` directory in CSP.
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
from alloy_data_extractor.extractors.microchip_csp_v2_1 import (  # noqa: E402
    extract_device as csp_extract,
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
    csp_root: Path | None,
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

    if csp_root is not None and csp_root.is_dir():
        csp_payload = csp_extract(
            vendor="microchip", family=family, device=device,
            csp_root=csp_root, atdf_path=atdf_path,
        )
        # Only count CSP as a source when it actually contributed
        # something (clock.domains populated).  An empty payload
        # is harmless but pollutes the provenance string.
        if csp_payload.get("clock", {}).get("domains"):
            enrichments.append(csp_payload)
            sources.append("microchip-csp")

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
    parser.add_argument("--family", required=True,
                        help="e.g. avr-da, same70, samd21, samd51")
    parser.add_argument("--pattern", required=True,
                        help="glob pattern matching ATDF files")
    parser.add_argument("--overlay-root", type=Path, default=ROOT / "data")
    parser.add_argument("--csp-root", type=Path, default=None,
                        help="Path to the cloned microchip-csp repo "
                             "(omit to skip the CSP enrichment).")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    matches = sorted(args.atdf_dir.glob(args.pattern))
    if not matches:
        print(f"ERROR: no ATDF matches {args.pattern} under {args.atdf_dir}",
              file=sys.stderr)
        return 1
    print(f"Re-emitting {len(matches)} {args.family} chip(s) into {args.out}")
    if args.csp_root is None:
        print("  (CSP source disabled — pass --csp-root to enable clock.domains)")
    print()

    failures = 0
    for atdf in matches:
        try:
            out_path, sources = _re_emit_one(
                atdf_path=atdf, family=args.family,
                overlay_root=args.overlay_root,
                csp_root=args.csp_root,
                output_root=args.out,
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
