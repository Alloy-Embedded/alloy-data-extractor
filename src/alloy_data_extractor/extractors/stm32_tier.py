"""STM32 tier-2/3/4 projector — secondary EnrichmentExtractor.

`complete-stm32-tier-coverage` Phase 2.

Walks every peripheral instance discovered in the CubeMX MCU XML,
looks up its IP version against the per-IP-version mapping
tables in :mod:`alloy_data_extractor.extractors.stm32_tier_mappings`,
and emits the canonical tier-2/3/4 arrays
(``adc_resolution_options``, ``uart_data_bits_options``,
``timer_prescaler_options``, etc.) the alloy-codegen runtime
trait builders consume.

Why hardcoded tables instead of projecting from SVD enums?

* CMSIS-SVD ``<enumeratedValues>`` would be the ideal upstream
  source, but the cmsis-svd-data community SVDs ship with
  uneven enum coverage — STM32G071's SVD has enums for ADC +
  TIM15 only, STM32F405's SVD has zero enums.
* The (human_value, raw_value) pairs are functions of the IP
  version (silicon design), not of the chip — so a small set of
  per-IP-version constant tables covers every chip in a family.
* Adding a new STM32 chip in an already-supported family
  becomes "stage SVD + CubeMX entry" without any code or data
  edit.

This extractor is **secondary**: it doesn't produce a primary
canonical YAML.  The merge engine (Phase 2.2) folds its output
onto a primary STM32 extraction via the
:data:`alloy_data_extractor.merge.STM32_MERGE_POLICY`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    MissingSourceError,
    ProvenanceRecord,
    register_extractor,
)
from alloy_data_extractor.extractors.stm32_cubemx import (
    _find_db_root,
    _match_mcu_xml,
    _parse_mcu_xml,
)
from alloy_data_extractor.extractors.stm32_tier_mappings import (
    ALL_TIER_MAPPINGS,
    TierMapping,
    find_tier_mapping,
)


@dataclass(frozen=True, slots=True)
class _ResolvedInstance:
    """A CubeMX peripheral instance paired with its tier mapping
    (or ``None`` when no mapping table covers the IP version)."""

    instance_name: str
    ip_name: str
    ip_version: str
    mapping: TierMapping | None


def _project_tier_arrays(
    instances: list[_ResolvedInstance],
) -> dict[str, list[dict[str, Any]]]:
    """Walk every resolved instance, fan its TierMapping
    projections out per-peripheral, and concatenate the rows by
    ``target_field``.

    Each row already carries ``peripheral: <instance_name>`` from
    the projection function — so two USART instances contribute
    independent rows tagged with their own names.  Cross-instance
    deduplication is **not** applied: the canonical YAML's
    tier arrays are per-peripheral.

    Final ordering: ``(peripheral, field_value, …)`` for byte-
    stable YAML output across runs.
    """
    aggregated: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in instances:
        if instance.mapping is None:
            continue
        for projection in instance.mapping.projections:
            rows = projection.project(instance.instance_name)
            aggregated[projection.target_field].extend(rows)

    out: dict[str, list[dict[str, Any]]] = {}
    for target_field, rows in aggregated.items():
        # Deterministic order: peripheral name → primary
        # discriminator (field_value / extsel_value / etc) →
        # full row repr as tiebreaker.
        rows.sort(
            key=lambda r: (
                r.get("peripheral", ""),
                r.get("field_value", 0),
                r.get("extsel_value", 0),
                r.get("m0_value", 0),
                r.get("m1_value", 0),
                r.get("pce_value", 0),
                r.get("ps_value", 0),
                r.get("prescaler_field_value", 0),
                str(r),
            )
        )
        out[target_field] = rows
    return out


def _resolve_instances(mcu_facts: Any) -> list[_ResolvedInstance]:
    """Pair each CubeMX peripheral instance with its TierMapping."""
    resolved: list[_ResolvedInstance] = []
    for peri in mcu_facts.peripheral_instances:
        mapping = find_tier_mapping(peri.ip_name, peri.ip_version)
        resolved.append(
            _ResolvedInstance(
                instance_name=peri.instance_name,
                ip_name=peri.ip_name,
                ip_version=peri.ip_version,
                mapping=mapping,
            )
        )
    return resolved


def _build_payload(
    *,
    request: ExtractionRequest,
    mcu_xml: Path,
    tier_arrays: dict[str, list[dict[str, Any]]],
    resolved: list[_ResolvedInstance],
) -> dict[str, Any]:
    """Assemble the canonical-IR-shaped enrichment payload."""
    return {
        "schema_version": "1.4.0",
        "identity": {
            "vendor": request.vendor,
            "family": request.family,
            "device": request.device,
            "core": "",
        },
        "provenance": {
            "source_id": "stm32-tier",
            "source_path": str(mcu_xml),
            "patch_ids": [
                f"stm32-tier@{request.revision}"
                if request.revision
                else "stm32-tier"
            ],
        },
        # Tier-3/4 arrays — empty dict-merge below, not field
        # spread, so callers can iterate `payload.keys()` to
        # discover which arrays got populated for this chip.
        **tier_arrays,
        # Surface the resolution log so reviewers can audit which
        # IP versions had no mapping (and would need a follow-up
        # mapping-table entry).
        "stm32_tier_resolution": [
            {
                "instance_name": r.instance_name,
                "ip_name": r.ip_name,
                "ip_version": r.ip_version,
                "mapped": r.mapping is not None,
            }
            for r in resolved
        ],
    }


@register_extractor(
    "stm32-tier",
    # Synthetic family — secondary extractor.  Merge engine
    # invokes it explicitly per `STM32_MERGE_POLICY`.
    families=(("__stm32_tier_secondary__", "__stm32_tier_secondary__"),),
)
class Stm32TierExtractor:
    """STM32 tier-2/3/4 secondary EnrichmentExtractor."""

    extractor_id: str = "stm32-tier"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        if "stm32cubemx-db" not in request.source_paths:
            raise MissingSourceError(
                "stm32-tier extractor needs source path keyed "
                "'stm32cubemx-db' (the CubeMX install root) so it "
                "can resolve per-peripheral IP versions.  Pass "
                "--source stm32cubemx-db=<path>.  "
                f"Got source keys: {sorted(request.source_paths)}"
            )

        supplied = request.source_paths["stm32cubemx-db"]
        roots = _find_db_root(supplied)
        if roots is None:
            raise ValueError(
                "stm32-tier extractor: cannot locate the CubeMX MCU "
                f"database under {supplied}.  Same path conventions "
                "as the stm32-cubemx extractor."
            )
        mcu_root, _ = roots  # clock_root not needed for tier projection

        mcu_xml = _match_mcu_xml(mcu_root, request.device)
        if mcu_xml is None:
            raise ValueError(
                f"stm32-tier extractor: no MCU XML in {mcu_root} "
                f"matches device {request.device!r}."
            )

        mcu_facts = _parse_mcu_xml(mcu_xml)
        resolved = _resolve_instances(mcu_facts)
        tier_arrays = _project_tier_arrays(resolved)

        payload = _build_payload(
            request=request,
            mcu_xml=mcu_xml,
            tier_arrays=tier_arrays,
            resolved=resolved,
        )

        warnings: list[str] = [
            "stm32-tier is a secondary enrichment — compose with a "
            "primary extraction via "
            "alloy_data_extractor.merge.merge_payloads(...).",
        ]
        unmapped = [r for r in resolved if r.mapping is None]
        if unmapped:
            unique_ips = sorted(
                {(r.ip_name, r.ip_version) for r in unmapped}
            )
            sample = ", ".join(
                f"{ip_name}@{ip_version}" for ip_name, ip_version in unique_ips[:5]
            )
            warnings.append(
                f"stm32-tier: {len(unmapped)} peripheral instance(s) "
                f"({len(unique_ips)} unique IP versions) had no "
                f"tier mapping — sample: {sample}.  Extend "
                "extractors/stm32_tier_mappings.py to cover them."
            )

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="stm32-tier",
                source_path=str(mcu_xml),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = [
    "ALL_TIER_MAPPINGS",
    "Stm32TierExtractor",
    "_project_tier_arrays",
    "_resolve_instances",
]
