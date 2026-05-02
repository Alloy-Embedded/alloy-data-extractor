#!/usr/bin/env python3
"""Validate alloy.device.v2.1 YAMLs against the JSON-schema.

Usage::

    python3 schema/validate.py <yaml-or-dir>... [--schema PATH]

Exit codes:
    0  every input validates clean
    1  one or more inputs failed validation
    2  invocation error (missing arg, schema not found, etc.)

The output is grouped per file and capped at the most relevant errors per
section so the report stays scrollable even on a big drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


SCHEMA_DEFAULT = Path(__file__).resolve().parent / "alloy-device-v2_1.schema.json"


# -----------------------------------------------------------------------------
# Loading helpers
# -----------------------------------------------------------------------------


class _StringDatesLoader(yaml.SafeLoader):
    """SafeLoader that keeps ISO-8601 date / datetime tokens as plain
    strings.  JSON-schema validates against strings; PyYAML otherwise
    auto-coerces ``2026-05-01`` to ``datetime.date``, which then fails
    a ``"type": "string"`` assertion.
    """


# Override the implicit resolver entry that maps date-shaped scalars to
# the timestamp tag.
_StringDatesLoader.yaml_implicit_resolvers = {
    ch: [(tag, regex) for tag, regex in entries if tag != "tag:yaml.org,2002:timestamp"]
    for ch, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _load_yaml(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_StringDatesLoader)


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_inputs(args: list[Path]) -> Iterator[Path]:
    """Expand directories to ``*.yml`` / ``*.yaml`` files; pass files
    through unchanged."""
    for arg in args:
        if arg.is_dir():
            yield from sorted(arg.glob("*.yml"))
            yield from sorted(arg.glob("*.yaml"))
        elif arg.is_file():
            yield arg
        else:
            print(f"WARN: input not found, skipping: {arg}", file=sys.stderr)


# -----------------------------------------------------------------------------
# Pretty error rendering
# -----------------------------------------------------------------------------


def _absolute_path(error: ValidationError) -> str:
    parts = [str(p) for p in error.absolute_path]
    return "/".join(parts) if parts else "<root>"


def _format_error(error: ValidationError, *, indent: str = "  ") -> str:
    path = _absolute_path(error)
    head = f"{indent}• {path}: {error.message}"
    # If we're inside a oneOf/anyOf, surface the schema path so the user
    # can tell which alternative was matched against.
    schema_path = list(error.absolute_schema_path)
    if schema_path:
        head += f"\n{indent}  (schema path: {'/'.join(str(p) for p in schema_path)})"
    return head


def _validate_one(payload: Any, validator: Draft202012Validator) -> list[ValidationError]:
    return sorted(
        validator.iter_errors(payload),
        key=lambda e: (list(e.absolute_path), e.message),
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="YAML files or directories to validate.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=SCHEMA_DEFAULT,
        help=f"Path to schema (default: {SCHEMA_DEFAULT}).",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=20,
        help="Cap the number of errors reported per file (default: 20).",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Print only failing files.",
    )
    args = parser.parse_args(argv)

    if not args.schema.is_file():
        print(f"ERROR: schema not found: {args.schema}", file=sys.stderr)
        return 2

    schema = _load_schema(args.schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    inputs = list(_iter_inputs(args.inputs))
    if not inputs:
        print("ERROR: no YAML inputs found.", file=sys.stderr)
        return 2

    failed = 0
    for path in inputs:
        try:
            payload = _load_yaml(path)
        except yaml.YAMLError as exc:
            failed += 1
            print(f"\033[31m{path}: YAML parse failed\033[0m\n  {exc}")
            continue

        errors = _validate_one(payload, validator)
        if errors:
            failed += 1
            shown = errors[: args.max_errors]
            extra = len(errors) - len(shown)
            print(f"\033[31m{path}: {len(errors)} schema error(s)\033[0m")
            for err in shown:
                print(_format_error(err))
            if extra > 0:
                print(f"  … and {extra} more (raise --max-errors to see all)")
        elif not args.quiet:
            print(f"\033[32m{path}: OK\033[0m")

    print()
    print(f"{len(inputs) - failed}/{len(inputs)} files passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
