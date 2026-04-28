"""Phase 1 extractor scaffolds — verifies that every admitted
vendor/family in alloy-codegen now resolves to its dedicated
extractor (Phase 1.x scaffold) rather than the catch-all
CMSIS-SVD extractor.

These tests do NOT exercise extraction itself — Phase 1.x
implementations land separately and replace the
``NotImplementedError`` stubs with real parsers.  This module
just locks the registration so the resolver picks the right
adapter the moment an implementation lands.

Note: the modm-devices enrichment extractor uses a synthetic
binding so it does NOT appear in resolver lookups.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor,
)

# (vendor, family) → expected extractor id once Phase 1 scaffold lands
_PHASE1_EXPECTATIONS = {
    ("st", "stm32f4"): "stm32",
    ("st", "stm32g0"): "stm32",
    ("microchip", "avr-da"): "microchip-dfp",
    ("microchip", "same70"): "microchip-dfp",
    ("nxp", "imxrt1060"): "nxp-mcux",
    ("raspberrypi", "rp2040"): "pico-sdk",
    ("espressif", "esp32"): "esp-idf",
    ("espressif", "esp32c3"): "esp-idf",
    ("espressif", "esp32s3"): "esp-idf",
    ("nordic", "nrf52"): "zephyr-dts",
}


@pytest.mark.parametrize(
    ("vendor", "family", "expected"),
    [(v, f, e) for (v, f), e in _PHASE1_EXPECTATIONS.items()],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_admitted_pair_resolves_to_dedicated_extractor(
    vendor: str, family: str, expected: str
) -> None:
    ext = resolve_extractor(vendor, family)
    assert ext.extractor_id == expected, (
        f"{vendor}/{family} resolved to {ext.extractor_id!r}; "
        f"expected {expected!r} via specificity over the catch-all."
    )


# Extractors that are still stubs (NotImplementedError-shaped).
# After the autonomous Phase-1 round, every primary extractor
# has a real implementation; the remaining stub is the secondary
# `modm-devices` enrichment which depends on Phase 2.2's
# cross-source merge engine.
_STILL_STUB: set[str] = set()


@pytest.mark.parametrize(
    ("vendor", "family", "extractor_id"),
    [
        (v, f, e)
        for (v, f), e in _PHASE1_EXPECTATIONS.items()
        if e in _STILL_STUB
    ],
)
def test_phase1_stubs_raise_not_implemented(
    vendor: str, family: str, extractor_id: str
) -> None:
    """Until Phase 1.x ports land, the dedicated extractor must
    raise a clear NotImplementedError pointing at the migration
    task — not a silent fallback to a partial implementation."""
    ext = resolve_extractor(vendor, family)
    request = ExtractionRequest(
        vendor=vendor,
        family=family,
        device="anydevice",
        source_paths={},
        revision="test",
    )
    with pytest.raises(NotImplementedError) as excinfo:
        ext.extract(request)
    msg = str(excinfo.value)
    # Every stub references the OpenSpec id.
    assert "Phase 1." in msg
    assert "migrate-" in msg


def test_modm_enrichment_does_not_appear_in_resolver() -> None:
    """modm-devices is a secondary extractor — it must not be
    pickable for any real vendor pair."""
    # Synthetic family the modm scaffold registered under.
    ext = resolve_extractor("__modm_secondary__", "__modm_secondary__")
    assert ext.extractor_id == "modm-devices"
    # And it must NOT win for any STM32 lookup.
    assert resolve_extractor("st", "stm32g0").extractor_id != "modm-devices"
