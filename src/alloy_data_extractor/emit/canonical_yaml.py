"""Canonical YAML writer.

Mirrors the determinism contract from
``alloy_codegen.canonical_device_yaml`` so files written here
load cleanly by alloy-codegen's consumer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

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

    Validates against the schema if ``schema_path`` is provided.
    """
    if schema_path is not None:
        validate(payload, schema_path)
    text = serialize(payload)
    out_path = output_root / "vendors" / vendor / family / "devices" / f"{device}.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path


__all__ = ["serialize", "validate", "write_device_yaml"]
