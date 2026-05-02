"""Canonical YAML writer — schema ``alloy.device.v2.1`` only.

After ``adopt-canonical-device-v2-1`` the legacy v1.x writer is gone.
This module provides a single entry-point that takes a v2.1 primitive
payload (dict matching the schema), validates it, and writes the
deterministic YAML form to disk.

Usage::

    from alloy_data_extractor.emit.canonical_yaml import write_device_yaml
    write_device_yaml(
        payload=v2_1_payload,
        output_root=Path("/path/to/alloy-devices-yml"),
        vendor="st",
        family="stm32g0",
        device="stm32g030f6",
    )

The validation hook delegates to alloy-codegen's bundled validator
when alloy-codegen is importable; otherwise it falls back to a local
schema cache.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

# v2.1 lock string — both the schema's `const` AND the emitted top-level value.
SCHEMA_VERSION_CURRENT = "alloy.device.v2.1"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Structured validation error for a YAML payload."""

    path: str
    message: str


# ---------------------------------------------------------------------------
# Schema discovery + validator cache
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_SCHEMA = _REPO_ROOT / "proposals" / "canonical-v2-handcrafted" / "schema" / "alloy-device-v2_1.schema.json"
_SIBLING_SCHEMA = _REPO_ROOT.parent / "alloy-codegen" / "schema" / "canonical_device_v2_1" / "alloy-device-v2_1.schema.json"


def _resolve_schema_path() -> Path:
    """Locate the v2.1 schema, preferring the codegen sibling clone."""
    for candidate in (_SIBLING_SCHEMA, _LOCAL_SCHEMA):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "v2.1 schema not found.  Looked at:\n"
        f"  • {_SIBLING_SCHEMA}\n"
        f"  • {_LOCAL_SCHEMA}\n"
        "Either check out alloy-codegen as a sibling or pin a copy "
        "under proposals/canonical-v2-handcrafted/schema/."
    )


_VALIDATOR_CACHE: Draft202012Validator | None = None


def _validator() -> Draft202012Validator:
    global _VALIDATOR_CACHE
    if _VALIDATOR_CACHE is None:
        schema = json.loads(_resolve_schema_path().read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _VALIDATOR_CACHE = Draft202012Validator(schema)
    return _VALIDATOR_CACHE


# ---------------------------------------------------------------------------
# Deterministic YAML dumper
# ---------------------------------------------------------------------------


# Top-level key order — matches alloy_codegen.canonical_device_v2_1
# `_TOP_LEVEL_KEY_ORDER`.
_TOP_LEVEL_KEY_ORDER: tuple[str, ...] = (
    "schema",
    "identity",
    "provenance",
    "memory",
    "clock",
    "templates",
    "peripherals",
    "pinout",
    "interrupts",
    "fuses",
    "system_examples",
)


class _CanonicalDumper(yaml.SafeDumper):
    """SafeDumper preserving dict insertion order, no anchors."""


def _represent_dict(dumper: _CanonicalDumper, data: dict) -> yaml.MappingNode:
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


_CanonicalDumper.add_representer(dict, _represent_dict)


def _ordered_top_level(payload: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    seen: set[str] = set()
    for key in _TOP_LEVEL_KEY_ORDER:
        if key in payload:
            ordered[key] = payload[key]
            seen.add(key)
    for key, value in payload.items():
        if key not in seen:
            ordered[key] = value
    return ordered


def serialize(payload: dict[str, Any]) -> str:
    """Render a v2.1 primitive payload as deterministic YAML text."""
    text = yaml.dump(
        _ordered_top_level(payload),
        Dumper=_CanonicalDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10_000,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text


# ---------------------------------------------------------------------------
# Validation entry-points
# ---------------------------------------------------------------------------


def validate(payload: dict[str, Any]) -> None:
    """Schema-validate the payload; raise ``ValueError`` on failure."""
    errors = sorted(_validator().iter_errors(payload), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    detail = "\n".join(
        f"  • {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    )
    raise ValueError(f"canonical YAML failed v2.1 schema validation:\n{detail}")


def validate_yaml_file(yaml_path: Path) -> tuple[ValidationIssue, ...]:
    """Load + validate a YAML file.  Returns the list of issues
    (empty when valid).  Filesystem / parse errors raise."""
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return (ValidationIssue(path="<root>", message="YAML root is not a mapping"),)
    issues: list[ValidationIssue] = []
    for error in sorted(_validator().iter_errors(payload), key=lambda e: list(e.absolute_path)):
        issues.append(
            ValidationIssue(
                path="/".join(str(p) for p in error.absolute_path) or "<root>",
                message=error.message,
            )
        )
    return tuple(issues)


def _enforce_schema_const(payload: dict[str, Any]) -> None:
    declared = payload.get("schema")
    if declared != SCHEMA_VERSION_CURRENT:
        raise ValueError(
            f"canonical YAML must declare schema={SCHEMA_VERSION_CURRENT!r}; "
            f"got {declared!r}.  See adopt-canonical-device-v2-1 for the "
            f"migration note."
        )


# ---------------------------------------------------------------------------
# Public writer
# ---------------------------------------------------------------------------


def write_device_yaml(
    *,
    payload: dict[str, Any],
    output_root: Path,
    vendor: str,
    family: str,
    device: str,
) -> Path:
    """Write a v2.1 canonical YAML to
    ``<output_root>/vendors/<v>/<f>/devices/<d>.yml``.

    Validates the payload (schema-const + JSON-schema) BEFORE any
    file I/O — a malformed payload never lands on disk.
    """
    _enforce_schema_const(payload)
    validate(payload)
    text = serialize(payload)
    out_path = output_root / "vendors" / vendor / family / "devices" / f"{device}.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path


__all__ = [
    "SCHEMA_VERSION_CURRENT",
    "ValidationIssue",
    "serialize",
    "validate",
    "validate_yaml_file",
    "write_device_yaml",
]
