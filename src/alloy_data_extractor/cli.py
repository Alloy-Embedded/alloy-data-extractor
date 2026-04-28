"""``alloy-data-extract`` CLI.

Subcommands:

* ``extract``  — run an extractor against one or more devices.
* ``index``    — rebuild ``index.yml`` by walking the YAML tree.
* ``dashboard``— rebuild ``coverage-dashboard.md`` from index.

The legacy "no subcommand, just flags" form keeps working as
``extract`` for back-compat — Phase 0/1 callers don't have to
update their invocations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alloy_data_extractor.dashboard import write_dashboard
from alloy_data_extractor.index import is_index_stale, write_index
from alloy_data_extractor.pipeline import (
    default_output_root,
    registered_extractors,
    run_extraction,
)


def _parse_source_arg(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in values:
        if "=" not in entry:
            raise argparse.ArgumentTypeError(f"--source must be key=value; got {entry!r}")
        key, _, value = entry.partition("=")
        result[key] = value
    return result


def _add_extract_args(parser: argparse.ArgumentParser) -> None:
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
        default=None,
        choices=[None, *registered_extractors()],
        help="Force a specific extractor; default auto-resolves from (vendor, family).",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="key=path source mapping (repeatable).  Keys may be device "
        "names (legacy) or source-ids (preferred, e.g. 'cmsis-svd').",
    )
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--schema", type=Path, default=None)
    parser.add_argument("--revision", default="unknown")


def _resolve_output_root(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    output_root = args.output_root or default_output_root()
    if not output_root.exists():
        parser.error(
            f"--output-root does not exist: {output_root}.  "
            "Clone alloy-devices-yml first or pass --output-root."
        )
    return output_root


def _cmd_extract(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    sources = _parse_source_arg(args.source)
    output_root = _resolve_output_root(args, parser)

    schema_path = args.schema
    if schema_path is None:
        candidate = output_root / "schema" / "canonical_device" / "device.schema.json"
        if candidate.exists():
            schema_path = candidate

    # Decide source-paths shape: device-keyed (legacy) or source-id-keyed (preferred).
    source_paths: dict[str, Path] = {}
    looks_device_keyed = all(key in args.device for key in sources)
    if looks_device_keyed and sources:
        source_paths = {d: Path(sources[d]) for d in args.device if d in sources}
    else:
        source_paths = {key: Path(value) for key, value in sources.items()}

    results = run_extraction(
        vendor=args.vendor,
        family=args.family,
        devices=args.device,
        extractor_id=args.extractor,
        source_paths=source_paths,
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


def _cmd_index(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    output_root = _resolve_output_root(args, parser)
    if args.check:
        stale, message = is_index_stale(data_repo_root=output_root)
        sys.stdout.write(message + "\n")
        return 1 if stale else 0
    out_path = write_index(data_repo_root=output_root)
    sys.stdout.write(f"Wrote {out_path}\n")
    return 0


def _cmd_dashboard(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    output_root = _resolve_output_root(args, parser)
    out_path = write_dashboard(data_repo_root=output_root)
    sys.stdout.write(f"Wrote {out_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alloy-data-extract",
        description=(
            "Extract canonical device YAML and maintain the "
            "alloy-devices-yml catalog."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    extract_parser = sub.add_parser("extract", help="Run an extractor (default).")
    _add_extract_args(extract_parser)

    index_parser = sub.add_parser(
        "index", help="Rebuild alloy-devices-yml/index.yml from the YAML tree."
    )
    index_parser.add_argument("--output-root", type=Path, default=None)
    index_parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if index.yml is stale (CI gate).",
    )

    dashboard_parser = sub.add_parser(
        "dashboard", help="Rebuild alloy-devices-yml/coverage-dashboard.md."
    )
    dashboard_parser.add_argument("--output-root", type=Path, default=None)

    # Backward-compat: when invoked with no subcommand, treat as 'extract'.
    args, remaining = parser.parse_known_args(argv)
    if args.command is None:
        # Re-parse with explicit 'extract' subcommand.
        return main(["extract", *(argv or sys.argv[1:])])

    if args.command == "extract":
        return _cmd_extract(args, extract_parser)
    if args.command == "index":
        return _cmd_index(args, index_parser)
    if args.command == "dashboard":
        return _cmd_dashboard(args, dashboard_parser)
    parser.error(f"unknown subcommand {args.command!r}")
    return 2  # unreachable


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
