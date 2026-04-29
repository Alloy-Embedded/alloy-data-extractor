"""Cross-source merge engine.

`add-cross-source-merge` (Phase 2.2 of the roadmap) folds
secondary enrichment payloads onto a primary extraction
payload according to a per-family :class:`MergePolicy`.

A real STM32 chip is described by **multiple** authoritative
sources, each better at some facets:

* **CMSIS-SVD**: register layout + IRQ table.  Weak on pinmux,
  almost no clock-tree edges.
* **STM32CubeMX DB**: pinmux + clock tree + DMA request matrix.
* **modm-devices**: enriched DMA + AF tables for STM32 and SAM.
* **Zephyr DTS**: cross-vendor pinmux + interrupts + memory
  regions, but no register layout.

The merge engine is deterministic: same inputs + same policy →
byte-identical output.  Every merged field carries per-field
provenance under ``provenance.field_provenance`` so reviewers
can audit which source supplied each value.

Public surface:

* :class:`MergePolicy` — declares per-field source priority.
* :func:`merge_payloads(primary, *enrichments, policy)` — folds
  enrichments onto a primary payload.

The schema bumps to 1.3.0 (additive, optional
``provenance.field_provenance``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Schema version produced by the merge engine.  When the merge
# is invoked, the output payload's schema_version is bumped so
# consumers know which optional fields to expect.
#
# 1.3.0 added ``provenance.field_provenance``.
# 1.4.0 added ``register_field_enumerations`` (the SVD enum
# projection that powers tier-3 option-array derivation).
MERGED_SCHEMA_VERSION = "1.4.0"


@dataclass(frozen=True, slots=True)
class MergePolicy:
    """Per-field source priority.

    Each entry maps a dotted field path (e.g.
    ``"peripherals[*].dma_bindings"``) to an ordered tuple of
    source-ids, most-preferred first.  When merging, the engine
    walks the priority list and uses the first source that
    actually supplies a non-empty value for that field.

    Top-level field shorthand: a key without bracket notation
    (e.g. ``"clock_nodes"``) means "the entire field at the
    root".
    """

    name: str
    primary_source_id: str
    field_priorities: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def priority_for(self, dotted_path: str) -> tuple[str, ...]:
        """Return the priority tuple for ``dotted_path``,
        falling back to ``(primary_source_id,)`` when the path
        is not in the policy."""
        if dotted_path in self.field_priorities:
            return self.field_priorities[dotted_path]
        return (self.primary_source_id,)


# Reference policy for STM32 — the one
# `migrate-modm-enrichment-extractor` calls into during the
# transitional period until Phase 2.2 wires it through the
# pipeline automatically.
STM32_MERGE_POLICY = MergePolicy(
    name="STM32",
    primary_source_id="stm32",
    field_priorities={
        # Pinmux / package pads: STM32 open-pin-data is the
        # authoritative source — it carries the package-specific
        # AF tables ST officially publishes.  CubeMX and modm
        # mostly mirror this; they fall back when open-pin-data
        # doesn't ship the chip yet.
        "pins": ("stm32-open-pin-data", "stm32-cubemx", "modm-devices", "stm32"),
        "package_pads": ("stm32-open-pin-data", "stm32-cubemx", "stm32"),
        "clock_nodes": ("modm-devices", "stm32-cubemx", "stm32"),
        "clock_selectors": ("modm-devices", "stm32-cubemx", "stm32"),
        "dma_requests": ("stm32-cubemx", "modm-devices", "stm32"),
        "dma_bindings": ("modm-devices", "stm32-cubemx", "stm32"),
        # Register layout: SVD wins.  Other sources can layer
        # in extra register fields if SVD is sparse.
        "registers": ("stm32", "modm-devices"),
        "register_fields": ("stm32", "modm-devices"),
    },
)


def _is_non_empty(value: Any) -> bool:
    """Treat empty list/tuple/dict/string as "no value supplied"
    so a fallback source can win.  ``None`` also means absent."""
    if value is None:
        return False
    if isinstance(value, list | tuple | dict | str):
        return len(value) > 0
    return True


def _payload_source_id(payload: dict[str, Any]) -> str:
    return str((payload.get("provenance") or {}).get("source_id", ""))


def _walk_field(
    payload_for_source: dict[str, dict[str, Any]],
    priority: tuple[str, ...],
    field_name: str,
) -> tuple[Any, str | None]:
    """Look at the priority order; return ``(value, source_id)``
    for the first source that supplies a non-empty value, else
    ``(None, None)``."""
    for source_id in priority:
        if source_id not in payload_for_source:
            continue
        value = payload_for_source[source_id].get(field_name)
        if _is_non_empty(value):
            return value, source_id
    return None, None


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Outcome of a merge run."""

    payload: dict[str, Any]
    field_provenance: dict[str, str]


def merge_payloads(
    *,
    primary: dict[str, Any],
    enrichments: tuple[dict[str, Any], ...] = (),
    policy: MergePolicy,
) -> MergeResult:
    """Fold enrichment payloads onto ``primary`` per ``policy``.

    Determinism contract:

    * Same inputs (down to dict ordering) + same policy →
      byte-identical output payload.
    * Every field whose value came from an enrichment carries a
      ``provenance.field_provenance[<field>] = <source_id>``
      entry; primary-sourced fields have provenance pointing at
      ``policy.primary_source_id``.
    * Output ``schema_version`` is bumped to
      :data:`MERGED_SCHEMA_VERSION`.
    """
    # Bucket payloads by source_id so the priority lookup is
    # cheap.
    payload_for_source: dict[str, dict[str, Any]] = {
        _payload_source_id(primary): primary,
    }
    for enrichment in enrichments:
        sid = _payload_source_id(enrichment)
        if not sid:
            continue
        # Last-write-wins on duplicate source-ids; merge engine
        # is not the place to resolve that.
        payload_for_source[sid] = enrichment

    merged: dict[str, Any] = {}
    field_provenance: dict[str, str] = {}

    # Walk every top-level field that any payload supplies.
    every_field: list[str] = []
    for payload in (primary, *enrichments):
        for key in payload:
            if key not in every_field:
                every_field.append(key)

    for field_name in every_field:
        if field_name in {"schema_version", "provenance"}:
            # We rebuild these explicitly below.
            continue
        priority = policy.priority_for(field_name)
        value, src = _walk_field(payload_for_source, priority, field_name)
        if value is None:
            # No source in policy supplies the field; fall back
            # to whichever payload had it first.
            for payload in (primary, *enrichments):
                if field_name in payload and _is_non_empty(payload[field_name]):
                    value = payload[field_name]
                    src = _payload_source_id(payload)
                    break
        if value is None:
            continue
        merged[field_name] = value
        field_provenance[field_name] = src or policy.primary_source_id

    # Stamp top-level fields.
    merged["schema_version"] = MERGED_SCHEMA_VERSION

    primary_provenance = dict(primary.get("provenance") or {})
    primary_provenance["source_id"] = policy.primary_source_id
    primary_provenance["field_provenance"] = field_provenance
    primary_provenance.setdefault("merge_policy", policy.name)
    primary_provenance.setdefault(
        "contributing_sources",
        sorted(payload_for_source),
    )
    merged["provenance"] = primary_provenance

    # Re-order: identity + provenance up front, then everything else
    # in the order the keys first appeared.
    ordered: dict[str, Any] = {"schema_version": merged["schema_version"]}
    if "identity" in merged:
        ordered["identity"] = merged["identity"]
    ordered["provenance"] = merged["provenance"]
    for key, value in merged.items():
        if key in ordered:
            continue
        ordered[key] = value

    return MergeResult(payload=ordered, field_provenance=field_provenance)


__all__ = [
    "MERGED_SCHEMA_VERSION",
    "MergePolicy",
    "MergeResult",
    "STM32_MERGE_POLICY",
    "merge_payloads",
]
