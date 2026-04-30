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
# 1.4.0 added (additive, optional) ``register_field_enumerations``
# under `complete-stm32-tier-coverage` (Phase 1) — projects every
# SVD ``<field><enumeratedValues><enumeratedValue>`` row.
# 1.5.0 added (additive, optional) ``provenance_defaults`` map
# under ``compact-canonical-yaml-and-cache-loads`` (Phase 2) —
# hoists the dominant per-section ``provenance`` block out of the
# rows so 5 936-row STM32 ``register_fields`` lists shrink ~30 %
# without information loss.  Readers expand back at parse time.
SCHEMA_VERSION_CURRENT = "1.5.0"

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
    # Provenance dedup map (1.5.0).
    "provenance_defaults",
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
    "register_field_enumerations",
    "cubemx_peripherals",
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
    # Tier-2/3/4 arrays projected by the `stm32-tier` extractor
    # under `complete-stm32-tier-coverage` Phase 2.  Order
    # mirrors the existing canonical YAML's tail layout.
    "adc_resolution_options",
    "adc_sample_time_options",
    "adc_oversampling_options",
    "adc_internal_channels",
    "adc_calibration_data_points",
    "adc_calibration_context",
    "adc_external_triggers",
    "adc_max_clock_hz",
    "uart_data_bits_options",
    "uart_parity_options",
    "uart_stop_bits_options",
    "uart_mode_flags",
    "uart_max_baud_hz",
    "spi_baud_prescaler_options",
    "spi_mode_flags",
    "i2c_speed_options",
    "i2c_timing_presets",
    "i2c_mode_flags",
    "timer_prescaler_options",
    "timer_trigger_sources",
    "timer_master_outputs",
    "timer_mode_flags",
    "pwm_alignment_options",
    "pwm_break_inputs",
    "pwm_deadtime_options",
    "pwm_mode_flags",
    # Diagnostic surface from stm32-tier — kept last so reviewers
    # can audit which IPs had no mapping table.
    "stm32_tier_resolution",
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


# ---------------------------------------------------------------------------
# Per-section provenance dedup — Phase 2 of
# ``compact-canonical-yaml-and-cache-loads``.
# ---------------------------------------------------------------------------

# Sections that historically carry per-row ``provenance`` blocks.
# Mirrors the alloy-codegen
# ``canonical_device_yaml._PROVENANCE_DEFAULT_SECTIONS`` set; kept
# in sync by hand because alloy-data-extractor owns its own writer
# (this module) and we'd rather not import the codegen helper here.
_PROVENANCE_DEFAULT_SECTIONS: tuple[str, ...] = (
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
    "register_field_enumerations",
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
    "cubemx_peripherals",
)


def _compact_provenance_defaults(
    payload: dict[str, Any],
    *,
    coverage_threshold: float = 0.5,
) -> dict[str, Any]:
    """For each row-list section, hoist the dominant
    ``provenance`` block to ``payload['provenance_defaults']
    [<section>]`` and drop it from rows whose provenance equals
    the default.  Rows whose provenance differs keep their own
    block.  Mutates ``payload`` in place AND returns it.

    Skips sections whose dominant provenance covers less than
    ``coverage_threshold`` of the section's rows — when there is
    no clear winner, per-row blocks are cheaper than the
    bookkeeping overhead.
    """
    from collections import Counter

    if not isinstance(payload, dict):
        return payload
    defaults: dict[str, dict[str, Any]] = dict(
        payload.get("provenance_defaults") or {},
    )
    for section_name in _PROVENANCE_DEFAULT_SECTIONS:
        rows = payload.get(section_name)
        if not isinstance(rows, list) or not rows:
            continue
        keyed: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            prov = row.get("provenance")
            if not isinstance(prov, dict):
                continue
            keyed.append((json.dumps(prov, sort_keys=True), prov))
        if not keyed:
            continue
        counter: Counter[str] = Counter(k for k, _ in keyed)
        top_key, top_count = counter.most_common(1)[0]
        if top_count / len(rows) < coverage_threshold:
            continue
        top_obj = next(prov for k, prov in keyed if k == top_key)
        defaults[section_name] = top_obj
        for row in rows:
            if not isinstance(row, dict):
                continue
            prov = row.get("provenance")
            if isinstance(prov, dict) and prov == top_obj:
                row.pop("provenance")
    if defaults:
        payload["provenance_defaults"] = defaults
    return payload


def serialize(payload: dict[str, Any]) -> str:
    """Render a canonical-IR payload as deterministic YAML.

    `compact-canonical-yaml-and-cache-loads` Phase 2: mutates
    ``payload`` to hoist dominant per-row ``provenance`` blocks
    into a top-level ``provenance_defaults`` map, dropping
    ~30 % of bytes on a typical STM32 YAML.  The reader
    (``alloy_codegen.canonical_device_yaml.parse_device``)
    expands them back so the IR's row dataclasses see fully-
    populated provenance fields.
    """
    _compact_provenance_defaults(payload)
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
