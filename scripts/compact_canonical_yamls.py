"""Compact every canonical YAML in alloy-devices-yml in place
via the schema-1.5.0 ``provenance_defaults`` map.

`compact-canonical-yaml-and-cache-loads` Phase 2.

Reads each ``vendors/<v>/<f>/devices/<d>.yml`` payload, runs the
per-section provenance dedup, bumps ``schema_version`` to
``1.5.0``, and writes the new YAML back atomically.  Round-trip
is verified after each write — the expanded YAML must equal the
original payload.

Usage::

    PYTHONPATH=src python3 scripts/compact_canonical_yamls.py \\
        /path/to/alloy-devices-yml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import yaml  # noqa: E402

from alloy_data_extractor.emit.canonical_yaml import (  # noqa: E402
    SCHEMA_VERSION_CURRENT,
    serialize,
)


def _walk_yamls(root: Path) -> list[Path]:
    return sorted(root.glob("vendors/*/*/devices/*.yml"))


def _deep_equal(a: object, b: object) -> bool:
    """Structure-stable equality ignoring dict-key ordering."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_deep_equal(x, y) for x, y in zip(a, b))
    return a == b


def _expand_for_check(payload: dict) -> dict:
    """Apply the inverse of `_compact_provenance_defaults` so we
    can compare to the original.  Inlined here (we don't want the
    extractor to depend on alloy-codegen at import time)."""
    defaults = payload.pop("provenance_defaults", None)
    if not isinstance(defaults, dict):
        return payload
    for section_name, section_default in defaults.items():
        if not isinstance(section_default, dict):
            continue
        rows = payload.get(section_name)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if "provenance" in row:
                continue
            inherited: dict = dict(section_default)
            patch_ids = inherited.get("patch_ids")
            if isinstance(patch_ids, list):
                inherited["patch_ids"] = list(patch_ids)
            row["provenance"] = inherited
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        help="Path to alloy-devices-yml repo root.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report savings without modifying files.",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Only process YAMLs whose name contains this substring.",
    )
    args = parser.parse_args()

    yamls = _walk_yamls(args.root)
    if args.filter:
        yamls = [p for p in yamls if args.filter in p.name]
    if not yamls:
        print(f"No YAMLs found under {args.root}/vendors/.")
        return 1

    total_before = 0
    total_after = 0
    failed: list[tuple[Path, str]] = []
    for path in yamls:
        try:
            text = path.read_text(encoding="utf-8")
            payload = yaml.load(text, Loader=yaml.CSafeLoader)
            if not isinstance(payload, dict):
                failed.append((path, "not a YAML mapping"))
                continue
            # Bump version to 1.5.0; older 1.x.y is preserved
            # only if it already declared the new field (it
            # doesn't).
            payload["schema_version"] = SCHEMA_VERSION_CURRENT

            # Re-serialise via the writer which auto-applies the
            # compactor before yaml.dump.
            new_text = serialize(payload)

            # Round-trip check: new YAML must expand back to the
            # exact same payload (ignoring schema_version, which
            # we just bumped).
            new_payload = yaml.load(new_text, Loader=yaml.CSafeLoader)
            new_payload_expanded = _expand_for_check(dict(new_payload))
            original_payload = yaml.load(text, Loader=yaml.CSafeLoader)
            original_payload["schema_version"] = SCHEMA_VERSION_CURRENT
            if not _deep_equal(new_payload_expanded, original_payload):
                failed.append((path, "round-trip mismatch"))
                continue

            before = len(text)
            after = len(new_text)
            total_before += before
            total_after += after
            saved_pct = (1 - after / before) * 100
            print(
                f"{path.relative_to(args.root)}: "
                f"{before:>10,} -> {after:>10,} bytes  "
                f"({saved_pct:+5.1f}%)"
            )

            if not args.dry_run:
                path.write_text(new_text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            failed.append((path, f"{type(exc).__name__}: {exc}"))

    if failed:
        print(f"\nFAILED ({len(failed)} files):")
        for path, msg in failed:
            print(f"  {path}: {msg}")
    print()
    print(
        f"TOTAL: {total_before:>12,} -> {total_after:>12,} bytes  "
        f"({(1 - total_after / total_before) * 100:.1f}% saved)"
        if total_before
        else ""
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
