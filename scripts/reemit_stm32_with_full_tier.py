"""Bulk re-emit the 5 admitted STM32 chips through the full tier
pipeline (`complete-stm32-tier-coverage` Phase 7).

Pipeline composition::

    SVD primary (registers + fields + enums)
      ⊕ stm32-cubemx (pinmux + DMA + clock + IP versions)
      ⊕ stm32-tier (per-IP-version tier-2/3/4 mapping projection)
      ⊕ stm32-overlay (family TOML constants + I2C TIMINGR)
      → merge_payloads → write_device_yaml

Outputs:

* One canonical YAML per chip in ``--output-root``.
* ``bulk-tier-report.json`` summarizing per-chip line counts,
  tier-field coverage, and drift counts vs the canonical YAML
  in alloy-devices-yml.
* ``bulk-tier-report.md`` rendering the same summary as a
  reviewable Markdown table.

Usage::

    PYTHONPATH=src python3 scripts/reemit_stm32_with_full_tier.py \\
        --cmsis-svd-root <path> --open-pin-data-root <path> \\
        --cubemx-db <path> --canonical-root <path> \\
        --output-root /tmp/stm32-bulk-reemit
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
import yaml  # noqa: E402
from alloy_data_extractor.emit.canonical_yaml import (  # noqa: E402
    write_device_yaml,
)
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor,
    resolve_extractor_by_id,
)
from alloy_data_extractor.merge import (  # noqa: E402
    STM32_MERGE_POLICY,
    merge_payloads,
)


# The 5 admitted STM32 devices in alloy-devices-yml today.
_ADMITTED_STM32_DEVICES: tuple[tuple[str, str], ...] = (
    ("stm32f4", "stm32f401re"),
    ("stm32f4", "stm32f405rg"),
    ("stm32g0", "stm32g030f6"),
    ("stm32g0", "stm32g071rb"),
    ("stm32g0", "stm32g0b1re"),
)


# Tier-2/3/4 fields the canonical YAMLs are expected to carry.
# Mirrors the requirement in
# openspec/changes/complete-stm32-tier-coverage/specs/vendor-coverage/spec.md.
_TIER_FIELDS: tuple[str, ...] = (
    "adc_resolution_options",
    "adc_sample_time_options",
    "adc_oversampling_options",
    "adc_internal_channels",
    "adc_calibration_data_points",
    "adc_calibration_context",
    "adc_external_triggers",
    "uart_data_bits_options",
    "uart_parity_options",
    "uart_stop_bits_options",
    "spi_baud_prescaler_options",
    "timer_prescaler_options",
    "timer_trigger_sources",
    "timer_master_outputs",
    "timer_mode_flags",
    "pwm_alignment_options",
    "pwm_break_inputs",
    "pwm_deadtime_options",
    "pwm_mode_flags",
    "i2c_speed_options",
    "i2c_timing_presets",
    "system_clock_profiles",
)


@dataclass
class ChipResult:
    family: str
    device: str
    output_path: str
    line_count: int
    canonical_line_count: int
    tier_fields_populated: list[str] = field(default_factory=list)
    tier_fields_missing: list[str] = field(default_factory=list)
    canonical_tier_fields: list[str] = field(default_factory=list)
    drift_per_field: dict[str, dict[str, int]] = field(default_factory=dict)
    contributing_sources: list[str] = field(default_factory=list)
    error: str | None = None


def _row_count(value: Any) -> int:
    """Count rows in a tier field's value; dict counts as 1, list as len()."""
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1
    return 1


def _process_chip(
    *,
    family: str,
    device: str,
    cmsis_svd_root: Path,
    open_pin_data_root: Path,
    cubemx_db: Path,
    canonical_root: Path,
    output_root: Path,
    revision: str,
) -> ChipResult:
    """Run the 4-way merge for one chip; returns a ChipResult."""
    primary_ext = resolve_extractor("st", family)
    primary = primary_ext.extract(
        ExtractionRequest(
            vendor="st",
            family=family,
            device=device,
            source_paths={
                "stm32": cmsis_svd_root,
                "stm32-open-pin-data": open_pin_data_root,
            },
            revision=revision,
        )
    )

    enrichments: list[dict[str, Any]] = []

    cubemx_ext = resolve_extractor_by_id("stm32-cubemx")
    enrichments.append(
        cubemx_ext.extract(
            ExtractionRequest(
                vendor="st",
                family=family,
                device=device,
                source_paths={"stm32cubemx-db": cubemx_db},
                revision=revision,
            )
        ).payload
    )

    tier_ext = resolve_extractor_by_id("stm32-tier")
    enrichments.append(
        tier_ext.extract(
            ExtractionRequest(
                vendor="st",
                family=family,
                device=device,
                source_paths={"stm32cubemx-db": cubemx_db},
                revision=revision,
            )
        ).payload
    )

    overlay_ext = resolve_extractor_by_id("stm32-overlay")
    enrichments.append(
        overlay_ext.extract(
            ExtractionRequest(
                vendor="st",
                family=family,
                device=device,
                source_paths={},
                revision=revision,
            )
        ).payload
    )

    merged = merge_payloads(
        primary=primary.payload,
        enrichments=tuple(enrichments),
        policy=STM32_MERGE_POLICY,
    )

    output_path = write_device_yaml(
        payload=merged.payload,
        output_root=output_root,
        vendor="st",
        family=family,
        device=device,
        schema_path=None,
    )
    line_count = sum(1 for _ in output_path.read_text(encoding="utf-8").splitlines())

    # Tier-field coverage on the re-emitted YAML.
    payload = merged.payload
    populated = [f for f in _TIER_FIELDS if f in payload and payload[f]]
    missing = [f for f in _TIER_FIELDS if f not in populated]

    # Compare against canonical (when present in alloy-devices-yml).
    canonical_path = (
        canonical_root / "vendors" / "st" / family / "devices" / f"{device}.yml"
    )
    canonical_line_count = 0
    canonical_tier_fields: list[str] = []
    drift_per_field: dict[str, dict[str, int]] = {}
    if canonical_path.exists():
        canonical_text = canonical_path.read_text(encoding="utf-8")
        canonical_line_count = sum(1 for _ in canonical_text.splitlines())
        canonical_payload = yaml.safe_load(canonical_text) or {}
        canonical_tier_fields = [
            f for f in _TIER_FIELDS if f in canonical_payload and canonical_payload[f]
        ]
        # Drift: compare row counts per tier field.
        for tier_field in _TIER_FIELDS:
            our_count = _row_count(payload.get(tier_field))
            their_count = _row_count(canonical_payload.get(tier_field))
            if our_count or their_count:
                drift_per_field[tier_field] = {
                    "reemit": our_count,
                    "canonical": their_count,
                    "delta": our_count - their_count,
                }

    contributing = (
        merged.payload.get("provenance", {}).get("contributing_sources") or []
    )

    return ChipResult(
        family=family,
        device=device,
        output_path=str(output_path),
        line_count=line_count,
        canonical_line_count=canonical_line_count,
        tier_fields_populated=populated,
        tier_fields_missing=missing,
        canonical_tier_fields=canonical_tier_fields,
        drift_per_field=drift_per_field,
        contributing_sources=list(contributing),
    )


def _render_markdown(results: list[ChipResult]) -> str:
    """Render the bulk run as a reviewable Markdown summary."""
    lines: list[str] = [
        "# STM32 Bulk Tier Re-Emit Report",
        "",
        "_Generated by `scripts/reemit_stm32_with_full_tier.py` —",
        "`complete-stm32-tier-coverage` Phase 7._",
        "",
        "## Summary",
        "",
        "| Device | Tier fields | Canonical | Re-emit lines | Canonical lines |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.device} | {len(r.tier_fields_populated)}/{len(_TIER_FIELDS)} | "
            f"{len(r.canonical_tier_fields)}/{len(_TIER_FIELDS)} | "
            f"{r.line_count:,} | {r.canonical_line_count:,} |"
        )
    lines.append("")
    lines.append("## Per-chip tier coverage")
    lines.append("")
    for r in results:
        lines.append(f"### {r.device}")
        lines.append("")
        lines.append(f"- contributing sources: `{', '.join(r.contributing_sources)}`")
        if r.tier_fields_missing:
            lines.append(
                f"- missing tier fields: `{', '.join(r.tier_fields_missing)}`"
            )
        else:
            lines.append("- missing tier fields: **none**")
        lines.append("")
        lines.append("| Tier field | Re-emit | Canonical | Δ |")
        lines.append("|---|---|---|---|")
        for tier_field in _TIER_FIELDS:
            row = r.drift_per_field.get(tier_field)
            if row is None:
                lines.append(f"| {tier_field} | 0 | 0 | 0 |")
            else:
                delta_marker = (
                    "+" if row["delta"] > 0 else ("" if row["delta"] == 0 else "-")
                )
                lines.append(
                    f"| {tier_field} | {row['reemit']} | "
                    f"{row['canonical']} | {delta_marker}{abs(row['delta'])} |"
                )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmsis-svd-root", type=Path, required=True)
    parser.add_argument("--open-pin-data-root", type=Path, required=True)
    parser.add_argument("--cubemx-db", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True,
                        help="Path to alloy-devices-yml repo root.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--revision", default="bulk-tier-reemit")
    parser.add_argument("--report", type=Path, default=None,
                        help="JSON report path (default <output-root>/bulk-tier-report.json).")
    args = parser.parse_args()

    results: list[ChipResult] = []
    for family, device in _ADMITTED_STM32_DEVICES:
        try:
            result = _process_chip(
                family=family,
                device=device,
                cmsis_svd_root=args.cmsis_svd_root,
                open_pin_data_root=args.open_pin_data_root,
                cubemx_db=args.cubemx_db,
                canonical_root=args.canonical_root,
                output_root=args.output_root,
                revision=args.revision,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {family}/{device}: {type(exc).__name__}: {exc}")
            results.append(
                ChipResult(
                    family=family,
                    device=device,
                    output_path="",
                    line_count=0,
                    canonical_line_count=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        print(
            f"{result.device:14s} : "
            f"{len(result.tier_fields_populated):2d}/{len(_TIER_FIELDS)} tier fields, "
            f"{result.line_count:>6,} lines (canonical {result.canonical_line_count:>6,})"
        )
        results.append(result)

    # Write JSON report.
    report_path = args.report or (args.output_root / "bulk-tier-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "family": r.family,
                        "device": r.device,
                        "output_path": r.output_path,
                        "line_count": r.line_count,
                        "canonical_line_count": r.canonical_line_count,
                        "tier_fields_populated": r.tier_fields_populated,
                        "tier_fields_missing": r.tier_fields_missing,
                        "canonical_tier_fields": r.canonical_tier_fields,
                        "drift_per_field": r.drift_per_field,
                        "contributing_sources": r.contributing_sources,
                        "error": r.error,
                    }
                    for r in results
                ]
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nJSON report written to {report_path}")

    # Markdown summary alongside.
    md_path = report_path.with_suffix(".md")
    md_path.write_text(_render_markdown(results), encoding="utf-8")
    print(f"Markdown report written to {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
