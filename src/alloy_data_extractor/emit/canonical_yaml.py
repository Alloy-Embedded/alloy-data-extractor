"""Canonical YAML writer.

Mirrors the determinism contract from
``alloy_codegen.canonical_device_yaml`` so files written here
load cleanly by alloy-codegen's consumer.

`lock-canonical-yaml-schema-v1` invariants:

* Every payload MUST carry ``schema_version`` matching the
  bundled schema; ``write_device_yaml`` refuses otherwise.
* Validation against the bundled schema is mandatory in writer
  and discoverable via :func:`validate_yaml_file`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

# The schema version this extractor writes.  Bumped via the
# documented semver rule (PATCH = additive optional, MINOR =
# additive required + backfill, MAJOR = incompatible).
#
# 1.3.0 added (additive, optional) ``provenance.field_provenance``
# under `add-cross-source-merge` (Phase 2.2).
SCHEMA_VERSION_CURRENT = "1.3.0"

_SEMVER_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Structured validation error for a YAML payload."""

    path: str
    message: str


def _semver_major(version: str) -> int:
    match = _SEMVER_RE.match(version)
    if match is None:
        raise ValueError(f"invalid semver: {version!r}")
    return int(match.group("major"))

# Top-level key order — must match alloy_codegen's
# canonical_device_yaml._TOP_LEVEL_KEY_ORDER exactly.
_TOP_LEVEL_KEY_ORDER: tuple[str, ...] = (
    "schema_version",
    "identity",
    "provenance",
    "memories",
    "packages",
    "package_pads",
    "pin_constraints",
    "pins",
    "ip_blocks",
    "peripherals",
    "interrupts",
    "interrupt_bindings",
    "vector_slots",
    "registers",
    "register_fields",
    "capabilities",
    "signal_endpoints",
    "route_requirements",
    "route_operations",
    "connection_candidates",
    "connection_groups",
    "system_clock_profiles",
    "clock_nodes",
    "clock_selectors",
    "clock_gates",
    "resets",
    "peripheral_clock_bindings",
    "dma_controllers",
    "dma_requests",
    "dma_bindings",
    "dma_routes",
    "startup_descriptors",
)


class _CanonicalDumper(yaml.SafeDumper):
    """SafeDumper preserving insertion-order on dict keys."""


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
    """Render a canonical-IR payload as deterministic YAML."""
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


def validate(payload: dict[str, Any], schema_path: Path) -> None:
    """Schema-validate a payload using the canonical device schema.

    Raises ``ValueError`` listing every error if validation fails.
    """
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    detail = "\n".join(
        f"  • {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors
    )
    raise ValueError(f"canonical YAML failed schema validation:\n{detail}")


def _enforce_schema_version(payload: dict[str, Any]) -> None:
    """`lock-canonical-yaml-schema-v1` invariant: every payload
    written through this module MUST declare a `schema_version`
    matching the bundled `SCHEMA_VERSION_CURRENT` major.
    """
    version = payload.get("schema_version")
    if not version:
        raise ValueError(
            "canonical YAML payload is missing required field "
            "`schema_version`. Set it to "
            f"{SCHEMA_VERSION_CURRENT!r} (current bundled schema)."
        )
    if not isinstance(version, str):
        raise ValueError(
            "canonical YAML field `schema_version` must be a "
            f"semver string; got {type(version).__name__}: {version!r}"
        )
    payload_major = _semver_major(version)
    bundled_major = _semver_major(SCHEMA_VERSION_CURRENT)
    if payload_major != bundled_major:
        raise ValueError(
            "canonical YAML payload `schema_version` major mismatch: "
            f"payload={version}, bundled={SCHEMA_VERSION_CURRENT}. "
            "Major bumps require coordinated changes in extractor + codegen + alloy-devices-yml."
        )


def validate_yaml_file(yaml_path: Path, schema_path: Path) -> tuple[ValidationIssue, ...]:
    """Load a YAML file and validate it against ``schema_path``.

    Returns a tuple of structured issues (empty if valid).  Does
    NOT raise on schema mismatch — callers decide whether to
    fail.  Always raises on filesystem / parse errors.
    """
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return (ValidationIssue(path="<root>", message="YAML root is not a mapping"),)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
        issues.append(
            ValidationIssue(
                path="/".join(str(p) for p in error.absolute_path) or "<root>",
                message=error.message,
            )
        )
    if "schema_version" not in payload:
        issues.insert(
            0,
            ValidationIssue(
                path="schema_version",
                message="required field `schema_version` is missing",
            ),
        )
    return tuple(issues)


def write_device_yaml(
    *,
    payload: dict[str, Any],
    output_root: Path,
    vendor: str,
    family: str,
    device: str,
    schema_path: Path | None = None,
) -> Path:
    """Write one ``vendors/<v>/<f>/devices/<d>.yml`` under
    ``output_root`` (typically a clone of alloy-devices-yml).

    `lock-canonical-yaml-schema-v1` invariants:

    * The payload MUST declare `schema_version` matching
      `SCHEMA_VERSION_CURRENT` major.
    * If `schema_path` is provided, the payload is schema-validated.

    Raises ``ValueError`` (no file written) on either failure.
    """
    _enforce_schema_version(payload)
    if schema_path is not None:
        validate(payload, schema_path)
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
