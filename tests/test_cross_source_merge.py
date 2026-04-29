"""Tests for `add-cross-source-merge` (Phase 2.2): merge engine
+ MergePolicy + per-field provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.merge import (  # noqa: E402
    MERGED_SCHEMA_VERSION,
    STM32_MERGE_POLICY,
    MergePolicy,
    merge_payloads,
)


def _stm32_primary() -> dict:
    return {
        "schema_version": "1.2.0",
        "identity": {
            "vendor": "st",
            "family": "stm32g0",
            "device": "stm32g071rb",
            "core": "cortex-m0plus",
        },
        "provenance": {"source_id": "stm32"},
        "peripherals": [{"name": "USART1", "base_address": 0x40013800}],
        "pins": [],
        "clock_nodes": [],
        "dma_bindings": [],
    }


def _modm_enrichment() -> dict:
    return {
        "schema_version": "1.2.0",
        "provenance": {"source_id": "modm-devices"},
        "clock_nodes": [{"id": "HSI16", "kind": "oscillator", "frequency": 16_000_000}],
        "dma_bindings": [{"peripheral": "USART1", "signal": "TX", "request_id": 17}],
    }


def _cubemx_enrichment() -> dict:
    return {
        "schema_version": "1.2.0",
        "provenance": {"source_id": "stm32-cubemx"},
        "pins": [{"name": "PA9", "alternate_functions": [{"af": 1, "signal": "USART1_TX"}]}],
        "dma_requests": [{"peripheral": "USART1", "signal": "TX", "request_id": 17}],
    }


def test_merge_picks_modm_for_clock_nodes() -> None:
    primary = _stm32_primary()
    result = merge_payloads(
        primary=primary,
        enrichments=(_modm_enrichment(),),
        policy=STM32_MERGE_POLICY,
    )
    assert result.payload["clock_nodes"]
    assert result.payload["clock_nodes"][0]["id"] == "HSI16"
    assert result.field_provenance["clock_nodes"] == "modm-devices"


def test_merge_picks_cubemx_for_pins() -> None:
    primary = _stm32_primary()
    result = merge_payloads(
        primary=primary,
        enrichments=(_modm_enrichment(), _cubemx_enrichment()),
        policy=STM32_MERGE_POLICY,
    )
    assert result.payload["pins"][0]["name"] == "PA9"
    assert result.field_provenance["pins"] == "stm32-cubemx"


def test_merge_falls_back_to_primary_for_registers() -> None:
    primary = _stm32_primary()
    primary["registers"] = [{"name": "CR1", "offset": 0}]
    result = merge_payloads(
        primary=primary,
        enrichments=(_modm_enrichment(),),
        policy=STM32_MERGE_POLICY,
    )
    assert result.payload["registers"][0]["name"] == "CR1"
    assert result.field_provenance["registers"] == "stm32"


def test_merge_bumps_schema_version() -> None:
    result = merge_payloads(
        primary=_stm32_primary(),
        enrichments=(),
        policy=STM32_MERGE_POLICY,
    )
    assert result.payload["schema_version"] == MERGED_SCHEMA_VERSION
    # 1.4.0 added register_field_enumerations under
    # complete-stm32-tier-coverage Phase 1.
    assert MERGED_SCHEMA_VERSION == "1.4.0"


def test_merge_records_contributing_sources() -> None:
    result = merge_payloads(
        primary=_stm32_primary(),
        enrichments=(_modm_enrichment(), _cubemx_enrichment()),
        policy=STM32_MERGE_POLICY,
    )
    contributing = result.payload["provenance"]["contributing_sources"]
    assert "stm32" in contributing
    assert "modm-devices" in contributing
    assert "stm32-cubemx" in contributing


def test_merge_is_deterministic_byte_for_byte() -> None:
    """Same inputs → same payload, modulo dict order
    (Python 3.7+ preserves insertion order)."""
    enrichments = (_modm_enrichment(), _cubemx_enrichment())
    a = merge_payloads(
        primary=_stm32_primary(), enrichments=enrichments, policy=STM32_MERGE_POLICY
    )
    b = merge_payloads(
        primary=_stm32_primary(), enrichments=enrichments, policy=STM32_MERGE_POLICY
    )
    assert a.payload == b.payload
    assert a.field_provenance == b.field_provenance


def test_merge_policy_default_priority_is_primary() -> None:
    policy = MergePolicy(name="X", primary_source_id="primary-x")
    assert policy.priority_for("foo") == ("primary-x",)


def test_merge_handles_empty_enrichments() -> None:
    """No enrichments → output equals primary payload (modulo
    schema_version bump + provenance enrichment)."""
    primary = _stm32_primary()
    primary["peripherals"] = [{"name": "USART1"}]
    result = merge_payloads(
        primary=primary,
        enrichments=(),
        policy=STM32_MERGE_POLICY,
    )
    assert result.payload["peripherals"] == primary["peripherals"]
    assert result.field_provenance["peripherals"] == "stm32"


def test_merge_skips_empty_fields_in_priority_chain() -> None:
    """When the higher-priority source supplies an empty list,
    the next source in the chain wins."""
    primary = _stm32_primary()
    cubemx = _cubemx_enrichment()
    cubemx["pins"] = []  # CubeMX is highest priority for pins; force fallback
    primary["pins"] = [{"name": "PA0"}]  # primary supplies fallback
    result = merge_payloads(
        primary=primary,
        enrichments=(_modm_enrichment(), cubemx),
        policy=STM32_MERGE_POLICY,
    )
    assert result.payload["pins"][0]["name"] == "PA0"
    assert result.field_provenance["pins"] == "stm32"


@pytest.mark.parametrize(
    ("field", "expected_winner"),
    [
        ("clock_nodes", "modm-devices"),
        ("clock_selectors", "modm-devices"),
        ("dma_bindings", "modm-devices"),
        ("pins", "stm32-open-pin-data"),
        ("dma_requests", "stm32-cubemx"),
    ],
)
def test_stm32_policy_field_priorities(field: str, expected_winner: str) -> None:
    """Each entry in STM32_MERGE_POLICY.field_priorities lists
    the priority chain head — that's the expected winner when
    every source supplies the field non-empty."""
    priority = STM32_MERGE_POLICY.priority_for(field)
    assert priority[0] == expected_winner
