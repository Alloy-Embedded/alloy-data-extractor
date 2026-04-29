"""Re-emit a STM32 device YAML by merging the primary STM32 extractor
with the CubeMX enrichment.

Usage::

    PYTHONPATH=src python3 scripts/reemit_stm32_with_cubemx.py \
        --device stm32g071rb \
        --family stm32g0 \
        --cmsis-svd-root <path-to-cmsis-svd-data> \
        --open-pin-data-root <path-to-STM32_open_pin_data> \
        --cubemx-db <path-to-CubeMX-install> \
        --output-root <path-to-alloy-devices-yml>

This is a one-off driver that mirrors what a future bulk-mode merge
flag will eventually run for every STM32 chip; for now it lets a
maintainer regenerate one device's YAML with CubeMX-derived AF
tables + DMA matrix + clock-tree edges merged in via
:data:`alloy_data_extractor.merge.STM32_MERGE_POLICY`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.emit.canonical_yaml import write_device_yaml  # noqa: E402
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor,
    resolve_extractor_by_id,
)
from alloy_data_extractor.merge import (  # noqa: E402
    STM32_MERGE_POLICY,
    merge_payloads,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, help="e.g. stm32g071rb")
    parser.add_argument("--family", required=True, help="e.g. stm32g0")
    parser.add_argument("--vendor", default="st")
    parser.add_argument("--cmsis-svd-root", type=Path, required=True)
    parser.add_argument("--open-pin-data-root", type=Path, required=True)
    parser.add_argument("--cubemx-db", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--revision", default="reemit-cubemx")
    parser.add_argument("--schema", type=Path, default=None)
    args = parser.parse_args()

    # Primary STM32 extraction (CMSIS-SVD + STM32 open-pin-data).
    primary_ext = resolve_extractor(args.vendor, args.family)
    primary = primary_ext.extract(
        ExtractionRequest(
            vendor=args.vendor,
            family=args.family,
            device=args.device,
            source_paths={
                "stm32": args.cmsis_svd_root,
                "stm32-open-pin-data": args.open_pin_data_root,
            },
            revision=args.revision,
        )
    )
    print(
        f"primary  {args.device}: {len(primary.payload.get('peripherals', []))} peripherals, "
        f"{len(primary.payload.get('pins', []))} pins, "
        f"{len(primary.payload.get('clock_nodes', []))} clock_nodes"
    )

    # CubeMX enrichment.
    cubemx_ext = resolve_extractor_by_id("stm32-cubemx")
    cubemx = cubemx_ext.extract(
        ExtractionRequest(
            vendor=args.vendor,
            family=args.family,
            device=args.device,
            source_paths={"stm32cubemx-db": args.cubemx_db},
            revision=args.revision,
        )
    )
    print(
        f"cubemx   {args.device}: {len(cubemx.payload.get('pins', []))} pins, "
        f"{len(cubemx.payload.get('dma_requests', []))} dma_requests, "
        f"{len(cubemx.payload.get('clock_nodes', []))} clock_nodes"
    )

    # Merge.
    merged = merge_payloads(
        primary=primary.payload,
        enrichments=(cubemx.payload,),
        policy=STM32_MERGE_POLICY,
    )
    print(
        f"merged   {args.device}: schema_version={merged.payload['schema_version']}, "
        f"contributing_sources="
        f"{merged.payload['provenance']['contributing_sources']}"
    )

    yaml_path = write_device_yaml(
        payload=merged.payload,
        output_root=args.output_root,
        vendor=args.vendor,
        family=args.family,
        device=args.device,
        schema_path=args.schema,
    )
    print(f"wrote    {yaml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
