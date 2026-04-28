"""``alloy-data-extract`` CLI.

Walks one ``(vendor, family)`` scope, runs the configured
extractor, and writes canonical YAML into the data repo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alloy_data_extractor.pipeline import (
    default_output_root,
    registered_extractors,
    run_extraction,
)


def _parse_source_arg(values: list[str]) -> dict[str, str]:
    """Parse repeated ``--source key=value`` flags into a dict."""
    result: dict[str, str] = {}
    for entry in values:
        if "=" not in entry:
            raise argparse.ArgumentTypeError(f"--source must be key=value; got {entry!r}")
        key, _, value = entry.partition("=")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alloy-data-extract",
        description=(
            "Extract canonical device YAML from authoritative vendor "
            "sources and write it into alloy-devices-yml."
        ),
    )
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument(
        "--device",
        action="append",
        required=True,
        help="Device name to extract (repeatable).",
    )
    parser.add_argument(
        "--extractor",
        default="cmsis-svd",
        choices=registered_extractors(),
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="device=path mapping for the extractor's source file (repeatable).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="alloy-devices-yml checkout root (defaults to sibling).",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to canonical_device/device.schema.json (validation off if absent).",
    )
    parser.add_argument(
        "--revision",
        default="unknown",
        help="Upstream revision identifier (recorded in provenance).",
    )
    args = parser.parse_args(argv)

    sources = _parse_source_arg(args.source)
    if missing := [d for d in args.device if d not in sources]:
        parser.error(
            f"--source missing for devices: {missing}.  Pass --source <device>=<path> per device."
        )

    output_root = args.output_root or default_output_root()
    if not output_root.exists():
        parser.error(
            f"--output-root does not exist: {output_root}.  Clone "
            "alloy-devices-yml first or pass --output-root."
        )

    schema_path = args.schema
    if schema_path is None:
        candidate = output_root / "schema" / "canonical_device" / "device.schema.json"
        if candidate.exists():
            schema_path = candidate

    results = run_extraction(
        vendor=args.vendor,
        family=args.family,
        devices=args.device,
        extractor_id=args.extractor,
        source_paths={d: Path(sources[d]) for d in args.device},
        output_root=output_root,
        revision=args.revision,
        schema_path=schema_path,
    )

    sys.stdout.write(f"Wrote {len(results)} device YAMLs to {output_root}:\n")
    for r in results:
        sys.stdout.write(
            f"  {r.vendor}/{r.family}/{r.device:18s}  {r.bytes_written:>9} bytes  "
            f"-> {r.yaml_path.relative_to(output_root)}\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
