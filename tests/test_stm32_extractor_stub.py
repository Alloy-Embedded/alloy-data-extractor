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


def test_stm32_extract_without_svd_path_raises_actionable_error() -> None:
    """Without a configured SVD path, the extractor surfaces a
    discoverable error pointing at the right --source flag."""
    ext = resolve_extractor("st", "stm32g0")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={},
        revision="test",
    )
    with pytest.raises(ValueError) as excinfo:
        ext.extract(request)
    msg = str(excinfo.value)
    assert "cmsis-svd" in msg
    assert "stm32g071rb" in msg


def test_stm32_extract_with_synthesized_svd_returns_payload(tmp_path: Path) -> None:
    """End-to-end: feed a minimal SVD via the cmsis-svd source
    key and confirm the extractor produces a canonical payload
    with provenance.source_id=stm32."""
    svd_text = """<?xml version="1.0"?>
<device>
  <name>STM32SYNTH</name>
  <description>Synthetic STM32 for tests</description>
  <cpu>
    <name>CM0</name>
    <revision>r0p0</revision>
  </cpu>
  <peripherals>
    <peripheral>
      <name>USART1</name>
      <baseAddress>0x40013800</baseAddress>
      <description>USART1</description>
      <interrupt>
        <name>USART1_IRQ</name>
        <value>27</value>
      </interrupt>
    </peripheral>
  </peripherals>
</device>
"""
    svd_path = tmp_path / "STM32SYNTH.svd"
    svd_path.write_text(svd_text, encoding="utf-8")

    ext = resolve_extractor("st", "stm32g0")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"cmsis-svd": svd_path},
        revision="test-rev",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["vendor"] == "st"
    assert result.payload["provenance"]["source_id"] == "stm32"
    assert result.payload["provenance"]["source_path"].endswith("STM32SYNTH.svd")
    assert any(p["name"] == "USART1" for p in result.payload["peripherals"])
    assert any(i["name"] == "USART1_IRQ" for i in result.payload["interrupts"])
    assert result.warnings  # warns about missing pinmux port

    # Per-row provenance was stamped by the cmsis_svd helpers and
    # then rewritten by the stm32 wrapper to match the top-level
    # source_id ("stm32" rather than "cmsis-svd").
    for peri in result.payload["peripherals"]:
        assert peri["provenance"]["source_id"] == "stm32"
        assert peri["provenance"]["source_path"] == "STM32SYNTH.svd"
    for interrupt in result.payload["interrupts"]:
        assert interrupt["provenance"]["source_id"] == "stm32"
