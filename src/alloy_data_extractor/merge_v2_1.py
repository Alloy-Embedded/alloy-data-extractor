"""Cross-source merge engine for v2.1 payloads.

Replaces the v1 ``merge.py`` (which understood the flat
``register_fields[]`` / ``pins[]`` layout) with one that operates on
the v2.1 hierarchy:

* Section-level priorities — ``pinout`` from CubeMX replaces SVD's
  placeholder; ``memory`` from an overlay TOML replaces the
  extractor stub; etc.
* Per-peripheral enrichment — ``peripherals[<id>].calibration`` from
  an overlay overlays the same instance in the primary, leaving
  other instances untouched.
* Per-template enrichment — ``templates.<ip>.options`` from
  ``stm32-tier`` adds named option lists to the SVD-derived
  template; per-bit ``fields`` collisions are won by the primary.
* Top-level provenance — primary's ``primary`` survives;
  enrichments stack into ``provenance.secondary[]``.

Determinism: same inputs + same policy → byte-identical output.

Public surface:

* :class:`MergePolicy`  — declarative priority record.
* :class:`MergeResult`  — output payload + per-section provenance.
* :func:`merge_payloads` — the merge entry-point.
* :data:`STM32_MERGE_POLICY` — STM32 reference policy.

Per-payload identity: each payload's ``provenance.primary`` is the
source-id used in priority lookups (``cmsis-svd:STM32G0B1.svd`` →
class ``cmsis-svd``).  The class is the substring before the first
``:``; this lets multiple SVDs from the same source bucket together.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


def _source_class(payload: dict[str, Any]) -> str:
    """Extract the source-class from ``provenance.primary``.

    ``cmsis-svd:STM32G0B1.svd`` → ``"cmsis-svd"``;
    ``stm32-open-pin-data`` (no colon) → returned verbatim.
    """
    prov = payload.get("provenance") or {}
    primary = str(prov.get("primary", ""))
    return primary.split(":", 1)[0] if primary else ""


def _is_non_empty(value: Any) -> bool:
    """Treat empty list/tuple/dict/string as 'no value supplied'."""
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, str)):
        return len(value) > 0
    return True


@dataclass(frozen=True, slots=True)
class MergePolicy:
    """Per-section + per-instance priority declaration.

    ``section_priorities`` maps a top-level section name (``"pinout"``,
    ``"memory"``, ``"clock"``) to a priority tuple of source-classes.
    The first source supplying a non-empty value for that section
    wins; falls back to primary if every source comes up empty.

    ``peripheral_field_priorities`` maps a per-peripheral-instance
    field name (``"calibration"``, ``"timing_presets"``,
    ``"external_triggers"``, ``"ip_version"``, ``"pin_options"``) to a
    priority tuple.  The merger looks up each peripheral by ``id``
    and folds the named field from the highest-priority enrichment.

    ``template_field_priorities`` maps a per-template field name
    (``"options"``, ``"trigger_sources"``, ``"master_outputs"``,
    ``"deadtime_options"``) to a priority tuple — same model,
    keyed by template id (``"adc"``, ``"usart"``, …).
    """

    name: str
    primary_source: str
    section_priorities: dict[str, tuple[str, ...]] = field(default_factory=dict)
    peripheral_field_priorities: dict[str, tuple[str, ...]] = field(default_factory=dict)
    template_field_priorities: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def section_priority(self, section: str) -> tuple[str, ...]:
        return self.section_priorities.get(section, (self.primary_source,))

    def peripheral_priority(self, field_name: str) -> tuple[str, ...]:
        return self.peripheral_field_priorities.get(
            field_name, (self.primary_source,),
        )

    def template_priority(self, field_name: str) -> tuple[str, ...]:
        return self.template_field_priorities.get(
            field_name, (self.primary_source,),
        )


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Outcome of a merge run."""

    payload: dict[str, Any]
    section_sources: dict[str, str]
    """Per-section provenance: which source-class supplied each
    top-level section in the merged output."""


# ---------------------------------------------------------------------------
# Section-level merge — first non-empty source per priority list
# ---------------------------------------------------------------------------


def _merge_sections(
    *,
    primary: dict[str, Any],
    enrichments: tuple[dict[str, Any], ...],
    policy: MergePolicy,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve every top-level key by source-class priority.

    Returns ``(merged_dict, per_section_source)`` where the dict is
    a fresh copy (not aliased to any input) so downstream mutations
    don't leak.
    """
    by_class: dict[str, dict[str, Any]] = {
        _source_class(primary): primary,
    }
    for e in enrichments:
        cls = _source_class(e)
        if cls:
            by_class.setdefault(cls, e)

    # Build the union of every section any payload supplies.
    every_section: list[str] = []
    seen = set()
    for payload in (primary, *enrichments):
        for key in payload:
            if key not in seen:
                every_section.append(key)
                seen.add(key)

    merged: dict[str, Any] = OrderedDict()
    section_sources: dict[str, str] = {}

    # Identity gets a shallow merge — primary wins per-key, enrichments
    # fill any holes (e.g. package from open-pin-data when SVD had none).
    primary_identity = primary.get("identity") or {}
    if isinstance(primary_identity, dict):
        identity = dict(primary_identity)
        for e in enrichments:
            e_identity = e.get("identity") or {}
            if isinstance(e_identity, dict):
                for k, v in e_identity.items():
                    if k not in identity or not _is_non_empty(identity[k]):
                        identity[k] = v
        merged["identity"] = identity
        section_sources["identity"] = policy.primary_source

    # Clock gets a per-key sub-section merge — multiple sources
    # contribute different parts (cubemx → topology, overlay →
    # profiles, modm → calibration cycles, …).  Priority:
    # ``clock.<sub>`` defaults to the same priority list as
    # ``clock`` but can be overridden via
    # ``policy.section_priorities["clock.<sub>"]``.
    clock_subkeys = ("oscillators", "domains", "profiles", "pll", "reset_state")
    if any(s == "clock" or s.startswith("clock.") for s in
           {*policy.section_priorities, "clock"}) and \
       any("clock" in p for p in (primary, *enrichments)):
        clock_block: dict[str, Any] = {}
        clock_default_priority = policy.section_priority("clock")
        for sub in clock_subkeys:
            sub_priority = policy.section_priorities.get(
                f"clock.{sub}", clock_default_priority,
            )
            chosen: Any = None
            for source_cls in sub_priority:
                payload = by_class.get(source_cls)
                if payload is None:
                    continue
                value = (payload.get("clock") or {}).get(sub)
                if _is_non_empty(value):
                    chosen = value
                    break
            if chosen is None:
                # Fallback: any payload with a non-empty value.
                for payload in (primary, *enrichments):
                    value = (payload.get("clock") or {}).get(sub)
                    if _is_non_empty(value):
                        chosen = value
                        break
            if chosen is not None:
                clock_block[sub] = chosen
        if clock_block:
            merged["clock"] = clock_block
            section_sources["clock"] = "merged"

    for section in every_section:
        if section in {"schema", "provenance", "identity", "clock"}:
            # rebuilt explicitly above (or later in caller)
            continue
        # Skip sections we'll merge per-instance below.
        if section in {"peripherals", "templates"}:
            continue

        priority = policy.section_priority(section)
        chosen_value: Any = None
        chosen_source: str | None = None
        for source_cls in priority:
            payload = by_class.get(source_cls)
            if payload is None:
                continue
            value = payload.get(section)
            if _is_non_empty(value):
                chosen_value = value
                chosen_source = source_cls
                break
        if chosen_value is None:
            # Fall back: any source that supplies something non-empty,
            # then the first explicit value (even empty) so schema-
            # required sections survive.
            for payload in (primary, *enrichments):
                if section in payload and _is_non_empty(payload[section]):
                    chosen_value = payload[section]
                    chosen_source = _source_class(payload)
                    break
            else:
                for payload in (primary, *enrichments):
                    if section in payload:
                        chosen_value = payload[section]
                        chosen_source = _source_class(payload)
                        break
        if chosen_value is None:
            continue
        merged[section] = chosen_value
        section_sources[section] = chosen_source or policy.primary_source
    return merged, section_sources


# ---------------------------------------------------------------------------
# Per-peripheral merge — instance-level field enrichment
# ---------------------------------------------------------------------------


def _index_peripherals(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{peripheral_id → row} for fast lookup."""
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("peripherals") or []:
        if isinstance(row, dict):
            id_ = row.get("id")
            if isinstance(id_, str):
                out[id_] = row
    return out


def _merge_peripherals(
    *,
    primary: dict[str, Any],
    enrichments: tuple[dict[str, Any], ...],
    policy: MergePolicy,
) -> list[dict[str, Any]]:
    """Walk peripherals from the primary, fold enrichment fields in
    by id.  Enrichments NEVER add new peripheral instances — only
    enrich existing ones the primary declared (the SVD is the
    source-of-truth for which silicon has which peripherals).
    """
    primary_pers = primary.get("peripherals") or []
    enrichment_index: dict[str, dict[str, dict[str, Any]]] = {
        _source_class(e): _index_peripherals(e) for e in enrichments
    }

    merged: list[dict[str, Any]] = []
    for primary_row in primary_pers:
        if not isinstance(primary_row, dict):
            continue
        out_row: dict[str, Any] = dict(primary_row)
        per_id = out_row.get("id")
        if not isinstance(per_id, str):
            merged.append(out_row)
            continue
        # For each enrichable field, walk the priority list and
        # take the first source that supplies a non-empty value.
        for fld, priority in policy.peripheral_field_priorities.items():
            for source_cls in priority:
                if source_cls == policy.primary_source:
                    # Primary already in out_row — only keep when it
                    # supplied a non-empty value.
                    if _is_non_empty(out_row.get(fld)):
                        break
                    continue
                payload_index = enrichment_index.get(source_cls, {})
                enrichment_row = payload_index.get(per_id)
                if enrichment_row and _is_non_empty(enrichment_row.get(fld)):
                    out_row[fld] = enrichment_row[fld]
                    break
        merged.append(out_row)
    return merged


# ---------------------------------------------------------------------------
# Per-template merge — IP-class enrichment
# ---------------------------------------------------------------------------


def _merge_templates(
    *,
    primary: dict[str, Any],
    enrichments: tuple[dict[str, Any], ...],
    policy: MergePolicy,
) -> dict[str, dict[str, Any]]:
    """Fold enrichment template fields (options / trigger_sources /
    master_outputs / deadtime_options / etc.) onto primary templates.

    Conservative: registers + fields ALWAYS come from primary (SVD
    is source-of-truth for register layout).  Enrichments only
    contribute named option / mapping blocks.
    """
    primary_templates = primary.get("templates") or {}
    enrichment_templates: dict[str, dict[str, Any]] = {}
    for e in enrichments:
        cls = _source_class(e)
        for ip, t in (e.get("templates") or {}).items():
            enrichment_templates.setdefault(f"{cls}|{ip}", t)

    merged: dict[str, dict[str, Any]] = {}
    for ip_name, primary_t in primary_templates.items():
        out: dict[str, Any] = dict(primary_t)
        for fld, priority in policy.template_field_priorities.items():
            for source_cls in priority:
                if source_cls == policy.primary_source:
                    if _is_non_empty(out.get(fld)):
                        break
                    continue
                key = f"{source_cls}|{ip_name}"
                t = enrichment_templates.get(key)
                if t and _is_non_empty(t.get(fld)):
                    out[fld] = t[fld]
                    break
        merged[ip_name] = out
    # Enrichments may declare templates the primary doesn't have
    # (e.g. an STM32 overlay can introduce a synthetic
    # ``timer_advanced``).  Append them in priority order.
    for ip_name in {ip for cls_ip in enrichment_templates for cls, ip in [cls_ip.split("|", 1)]}:
        if ip_name in merged:
            continue
        for e in enrichments:
            t = (e.get("templates") or {}).get(ip_name)
            if t:
                merged[ip_name] = dict(t)
                break
    return merged


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def merge_payloads(
    *,
    primary: dict[str, Any],
    enrichments: tuple[dict[str, Any], ...] = (),
    policy: MergePolicy,
) -> MergeResult:
    """Compose ``primary`` with enrichments per ``policy``.

    Determinism contract:

    * Same inputs (down to dict ordering) + same policy →
      byte-identical output payload.
    * The output's ``schema`` is always ``alloy.device.v2.1``.
    * ``provenance.primary`` carries the primary's primary;
      ``provenance.secondary[]`` carries every contributing
      enrichment's provenance.primary, in declaration order.
    """
    merged, section_sources = _merge_sections(
        primary=primary, enrichments=enrichments, policy=policy,
    )
    merged_peripherals = _merge_peripherals(
        primary=primary, enrichments=enrichments, policy=policy,
    )
    merged_templates = _merge_templates(
        primary=primary, enrichments=enrichments, policy=policy,
    )

    # Build the output in canonical key order.
    out: dict[str, Any] = OrderedDict()
    out["schema"] = "alloy.device.v2.1"
    if "identity" in merged:
        out["identity"] = merged["identity"]

    # Compose provenance.
    primary_prov = dict(primary.get("provenance") or {})
    primary_prov.setdefault("primary", "unknown")
    secondary = list(primary_prov.get("secondary") or ())
    for e in enrichments:
        e_prov = e.get("provenance") or {}
        e_primary = e_prov.get("primary")
        if e_primary and e_primary not in secondary and e_primary != primary_prov["primary"]:
            secondary.append(str(e_primary))
    if secondary:
        primary_prov["secondary"] = secondary
    out["provenance"] = primary_prov

    if "memory" in merged:
        out["memory"] = merged["memory"]
    if "clock" in merged:
        out["clock"] = merged["clock"]
    if merged_templates:
        out["templates"] = merged_templates
    if merged_peripherals:
        out["peripherals"] = merged_peripherals
    if "pinout" in merged:
        out["pinout"] = merged["pinout"]
    if "interrupts" in merged:
        out["interrupts"] = merged["interrupts"]
    # Carry every other section through.
    for key, value in merged.items():
        if key in {"identity", "memory", "clock", "pinout", "interrupts"}:
            continue
        out.setdefault(key, value)

    return MergeResult(payload=out, section_sources=section_sources)


# ---------------------------------------------------------------------------
# Reference policy: STM32
# ---------------------------------------------------------------------------


STM32_MERGE_POLICY = MergePolicy(
    name="stm32",
    primary_source="cmsis-svd",
    section_priorities={
        "memory":             ("stm32-overlay", "stm32-cubemx", "cmsis-svd"),
        "pinout":             ("stm32-open-pin-data", "stm32-cubemx", "cmsis-svd"),
        "interrupts":         ("cmsis-svd",),
        # Sub-section priorities for clock — cubemx owns the
        # topology (oscillators + domains + select_register
        # encodings); overlay owns the named profiles + reset_state;
        # both contribute to the merged clock block.
        "clock.oscillators":  ("stm32-cubemx", "stm32-overlay", "cmsis-svd"),
        "clock.domains":      ("stm32-cubemx", "stm32-overlay", "cmsis-svd"),
        "clock.pll":          ("stm32-cubemx", "stm32-overlay"),
        "clock.profiles":     ("stm32-overlay", "stm32-cubemx"),
        "clock.reset_state":  ("stm32-overlay", "stm32-cubemx", "cmsis-svd"),
    },
    peripheral_field_priorities={
        "ip_version":         ("stm32-open-pin-data", "stm32-cubemx", "cmsis-svd"),
        "pin_options":        ("stm32-open-pin-data", "stm32-cubemx"),
        "calibration":        ("stm32-overlay",),
        "external_triggers":  ("stm32-tier", "stm32-cubemx", "stm32-overlay"),
        "timing_presets":     ("stm32-overlay",),
        "channels":           ("stm32-cubemx", "stm32-overlay"),
        "dma":                ("stm32-cubemx", "modm-devices"),
        "max_clock_override": ("stm32-overlay", "stm32-cubemx"),
    },
    template_field_priorities={
        "options":            ("stm32-tier", "stm32-overlay"),
        "trigger_sources":    ("stm32-tier",),
        "master_outputs":     ("stm32-tier",),
        "deadtime_options":   ("stm32-tier",),
        "break_inputs":       ("stm32-tier",),
        "max_clock":          ("stm32-overlay", "stm32-tier"),
        "max_baud":           ("stm32-overlay",),
    },
)


__all__ = [
    "MergePolicy",
    "MergeResult",
    "STM32_MERGE_POLICY",
    "merge_payloads",
]
