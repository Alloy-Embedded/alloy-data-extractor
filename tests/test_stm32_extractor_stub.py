"""Tests for the STM32 extractor scaffold (Phase 1.1, additive).

The full parser port (CMSIS-SVD + STM32_open_pin_data) lands in
the daytime continuation of the migration.  Tonight's autonomous
work just locks in:

* the registration (so the resolver picks STM32 specifically for
  ST families),
* the deferring stub that surfaces a clear NotImplementedError
  with a pointer at the migration task.
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
    resolve_extractor_by_id,
)


def test_stm32_resolves_for_admitted_st_families() -> None:
    for family in ("stm32f4", "stm32g0"):
        ext = resolve_extractor("st", family)
        assert ext.extractor_id == "stm32", (
            f"resolver picked {ext.extractor_id!r} for st/{family} — "
            "expected stm32 (family-specific) to win over cmsis-svd (vendor-wide)."
        )


def test_stm32_extractor_is_registered() -> None:
    ext = resolve_extractor_by_id("stm32")
    assert ext.extractor_id == "stm32"


def test_stm32_extract_raises_not_implemented_with_actionable_message() -> None:
    """Until Phase 1.1's full port lands, calling extract() must
    surface a clear pointer at the migration — not a silent
    fallback to a half-complete CMSIS-SVD pass."""
    ext = resolve_extractor("st", "stm32g0")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={},
        revision="test",
    )
    with pytest.raises(NotImplementedError) as excinfo:
        ext.extract(request)
    msg = str(excinfo.value)
    assert "Phase 1.1" in msg
    assert "migrate-stm32-extractor" in msg
