"""End-to-end test: modm enrichment composes with the STM32
primary extraction via the merge engine.

Validates Phase 1.7 (modm port) + Phase 2.2 (merge engine) +
Phase 1.1 (STM32 extractor) all working together.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor,
    resolve_extractor_by_id,
)
from alloy_data_extractor.merge import (  # noqa: E402
    MERGED_SCHEMA_VERSION,
    STM32_MERGE_POLICY,
    merge_payloads,
)

# Reach into alloy-codegen's local cache for the cmsis-svd data
# and into its fixtures for the modm XML.  Both are guaranteed to
# exist on this workstation; CI rehydrates them via source pins.
_CMSIS_ROOT = Path(
    "/Users/lgili/Documents/01 - Codes/01 - Github/alloy-codegen/.claude/worktrees/"
    "youthful-ramanujan-9c9225/.cache/sources/cmsis-svd-data"
)
_MODM_FIXTURE = Path(
    "/Users/lgili/Documents/01 - Codes/01 - Github/alloy-codegen/.claude/worktrees/"
    "youthful-ramanujan-9c9225/tests/fixtures/modm-devices/devices/stm32/g0/stm32g071rb.xml"
)


def test_stm32_plus_modm_merge_layers_clock_tree_and_dma() -> None:
    """Realistic flow: stm32 primary → modm enrichment → merge.

    The merged payload's ``clock_nodes`` and ``dma_bindings``
    come from modm; ``peripherals`` and ``identity`` come from
    stm32.  ``provenance.field_provenance`` records the source
    of every merged field.
    """
    if not _CMSIS_ROOT.exists():
        import pytest

        pytest.skip(f"cmsis-svd-data cache missing at {_CMSIS_ROOT}")
    if not _MODM_FIXTURE.exists():
        import pytest

        pytest.skip(f"modm fixture missing at {_MODM_FIXTURE}")

    # 1. Primary STM32 extraction.
    stm32_ext = resolve_extractor("st", "stm32g0")
    primary = stm32_ext.extract(
        ExtractionRequest(
            vendor="st",
            family="stm32g0",
            device="stm32g071rb",
            source_paths={"stm32": _CMSIS_ROOT},
            revision="cmsis-test",
        )
    ).payload

    # 2. modm enrichment.
    modm_ext = resolve_extractor_by_id("modm-devices")
    enrichment = modm_ext.extract(
        ExtractionRequest(
            vendor="st",
            family="stm32g0",
            device="stm32g071rb",
            source_paths={"modm-xml": _MODM_FIXTURE},
            revision="modm-test-pin",
        )
    ).payload

    # 3. Merge them.
    merged = merge_payloads(
        primary=primary,
        enrichments=(enrichment,),
        policy=STM32_MERGE_POLICY,
    )

    # 4. Assertions.
    assert merged.payload["schema_version"] == MERGED_SCHEMA_VERSION
    # peripherals come from stm32 primary
    assert merged.field_provenance["peripherals"] == "stm32"
    assert any(p["name"] == "USART1" for p in merged.payload["peripherals"])
    # clock_nodes come from modm
    assert merged.field_provenance["clock_nodes"] == "modm-devices"
    assert any(n["id"] == "hsi16" for n in merged.payload["clock_nodes"])
    # dma_bindings come from modm
    assert merged.field_provenance["dma_bindings"] == "modm-devices"
    assert merged.payload["dma_bindings"]
    # contributing_sources records both
    contributing = merged.payload["provenance"]["contributing_sources"]
    assert "stm32" in contributing
    assert "modm-devices" in contributing
    # field_provenance lives under provenance
    assert merged.payload["provenance"]["field_provenance"] == merged.field_provenance
