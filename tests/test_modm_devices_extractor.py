"""Unit tests for the modm-devices extractor (Phase 1.7).

Synthetic-XML focused tests + a fixture-backed end-to-end
exercising the merge integration.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor_by_id,
)
from alloy_data_extractor.extractors.modm_devices import (  # noqa: E402
    _parse_modm_xml,
)


def _write_xml(tmp_path: Path) -> Path:
    text = textwrap.dedent("""\
        <?xml version="1.0"?>
        <device device-name="synth" platform="stm32" family="g0">
          <attribute name="core">cortex-m0plus</attribute>
          <driver name="rcc" type="stm32">
            <signal source="hsi16" target="sysclk"/>
            <signal source="hse" target="sysclk"/>
            <signal source="hsi16" target="pll_in"/>
            <signal source="pll_in" target="pll_r" multiplier="8"/>
          </driver>
          <driver name="dma" type="stm32-mux">
            <request name="USART1_RX" peripheral="USART1" signal="RX" channel="50"/>
            <request name="USART1_TX" peripheral="USART1" signal="TX" channel="51"/>
          </driver>
          <driver name="gpio" type="stm32">
            <gpio port="A" pin="9">
              <signal driver="usart" instance="1" name="tx" af="1"/>
            </gpio>
            <gpio port="A" pin="10">
              <signal driver="usart" instance="1" name="rx" af="1"/>
            </gpio>
          </driver>
        </device>
    """)
    path = tmp_path / "synth.xml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_extracts_clock_edges(tmp_path: Path) -> None:
    edges, _, _ = _parse_modm_xml(_write_xml(tmp_path))
    edge_ids = {(e.source, e.target) for e in edges}
    assert ("hsi16", "sysclk") in edge_ids
    assert ("hse", "sysclk") in edge_ids
    pll_edge = next(e for e in edges if e.source == "pll_in" and e.target == "pll_r")
    assert pll_edge.multiplier == 8


def test_parse_extracts_dma_requests(tmp_path: Path) -> None:
    _, dma, _ = _parse_modm_xml(_write_xml(tmp_path))
    by_signal = {(r.peripheral, r.signal): r.request_value for r in dma}
    assert by_signal[("USART1", "RX")] == 50
    assert by_signal[("USART1", "TX")] == 51


def test_parse_extracts_signal_afs(tmp_path: Path) -> None:
    _, _, afs = _parse_modm_xml(_write_xml(tmp_path))
    by_pin = {a.pin: a for a in afs}
    assert by_pin["PA9"].peripheral == "USART1"
    assert by_pin["PA9"].signal == "tx"
    assert by_pin["PA9"].af_number == 1
    assert by_pin["PA10"].signal == "rx"


def test_extractor_payload_carries_clock_selector_for_multi_input_target(tmp_path: Path) -> None:
    """sysclk has two sources (hsi16, hse) — the projected
    payload exposes that as a clock_selector with two
    parent_options."""
    xml = _write_xml(tmp_path)
    ext = resolve_extractor_by_id("modm-devices")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="synth",
        source_paths={"modm-xml": xml},
        revision="r",
    )
    result = ext.extract(request)
    selectors = result.payload["clock_selectors"]
    by_id = {s["id"]: s for s in selectors}
    assert "sysclk" in by_id
    assert set(by_id["sysclk"]["parent_options"]) == {"hsi16", "hse"}


def test_extractor_payload_aggregates_pins(tmp_path: Path) -> None:
    xml = _write_xml(tmp_path)
    ext = resolve_extractor_by_id("modm-devices")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="synth",
        source_paths={"modm-xml": xml},
        revision="r",
    )
    pins = ext.extract(request).payload["pins"]
    by_name = {p["name"]: p for p in pins}
    assert by_name["PA9"]["alternate_functions"] == [
        {"af": 1, "peripheral": "USART1", "signal": "tx"}
    ]


def test_extractor_raises_when_xml_missing(tmp_path: Path) -> None:
    ext = resolve_extractor_by_id("modm-devices")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="synth",
        source_paths={},
        revision="r",
    )
    with pytest.raises(ValueError, match="modm-devices"):
        ext.extract(request)


def test_extractor_does_not_win_resolver_for_st_family() -> None:
    """modm is secondary — must not auto-resolve for ST."""
    from alloy_data_extractor.extractor_protocol import resolve_extractor

    ext = resolve_extractor("st", "stm32g0")
    assert ext.extractor_id == "stm32"  # primary wins, modm is secondary
