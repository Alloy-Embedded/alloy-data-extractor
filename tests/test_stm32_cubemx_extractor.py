"""Tests for the STM32 CubeMX extractor (Phase 3.2,
`add-stm32-cubemx-db-extractor`).

The bulk of the suite uses synthetic fixtures so it runs offline.
Two opt-in real-DB tests exercise the extractor against a locally
installed STM32CubeMX (defaults to the macOS path) covering the
F0 / F4 / G0 series the OpenSpec calls out.
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
    MissingSourceError,
    resolve_extractor,
    resolve_extractor_by_id,
)
from alloy_data_extractor.extractors.stm32_cubemx import (  # noqa: E402
    _canonical_pin_name,
    _expand_variants,
    _match_mcu_xml,
    _parse_clocktree_xml,
    _parse_dma_ip_xml,
    _parse_gpio_ip_xml,
    _parse_mcu_xml,
)


# ---------------------------------------------------------------------------
# Synthetic fixture builders
# ---------------------------------------------------------------------------


def _build_synthetic_db(tmp_path: Path) -> Path:
    """Lay out a minimal CubeMX-style ``db/`` tree backing a
    fictional STM32G071R(6-8-B)Tx + GPIO IP + DMA IP + clock tree.
    Returns the ``db`` root path the extractor should be pointed at.
    """
    db = tmp_path / "db"
    mcu_dir = db / "mcu"
    ip_dir = mcu_dir / "IP"
    clock_dir = db / "plugins" / "clock"
    for d in (mcu_dir, ip_dir, clock_dir):
        d.mkdir(parents=True)

    (mcu_dir / "STM32G071R(6-8-B)Tx.xml").write_text(
        textwrap.dedent("""\
            <?xml version="1.0"?>
            <Mcu xmlns="http://mcd.rou.st.com/modules.php?name=mcu"
                 RefName="STM32G071R(6-8-B)Tx" Family="STM32G0"
                 Line="STM32G0x1" ClockTree="STM32G0">
              <Core>ARM Cortex-M0+</Core>
              <IP InstanceName="GPIO" Name="GPIO" Version="STM32G07x_gpio_v1_0"/>
              <IP InstanceName="DMA"  Name="DMA"  Version="STM32G081_dma1_v1_3"/>
              <Pin Name="PA9 (PA9)" Position="20" Type="I/O">
                <Signal Name="USART1_TX"/>
                <Signal Name="GPIO"/>
              </Pin>
              <Pin Name="PA10" Position="21" Type="I/O">
                <Signal Name="USART1_RX"/>
                <Signal Name="GPIO"/>
              </Pin>
              <Pin Name="PC14-OSC32_IN (PC14)" Position="2" Type="I/O">
                <Signal Name="GPIO"/>
              </Pin>
              <Pin Name="VDD" Position="1" Type="Power"/>
            </Mcu>
        """),
        encoding="utf-8",
    )

    (ip_dir / "GPIO-STM32G07x_gpio_v1_0_Modes.xml").write_text(
        textwrap.dedent("""\
            <?xml version="1.0"?>
            <IP xmlns="http://mcd.rou.st.com/modules.php?name=mcu"
                Name="GPIO" Version="STM32G07x_gpio_v1_0">
              <GPIO_Pin PortName="PA" Name="PA9">
                <PinSignal Name="USART1_TX">
                  <SpecificParameter Name="GPIO_AF">
                    <PossibleValue>GPIO_AF1_USART1</PossibleValue>
                  </SpecificParameter>
                </PinSignal>
                <PinSignal Name="I2C1_SCL">
                  <SpecificParameter Name="GPIO_AF">
                    <PossibleValue>GPIO_AF6_I2C1</PossibleValue>
                  </SpecificParameter>
                </PinSignal>
              </GPIO_Pin>
              <GPIO_Pin PortName="PA" Name="PA10">
                <PinSignal Name="USART1_RX">
                  <SpecificParameter Name="GPIO_AF">
                    <PossibleValue>GPIO_AF1_USART1</PossibleValue>
                  </SpecificParameter>
                </PinSignal>
              </GPIO_Pin>
            </IP>
        """),
        encoding="utf-8",
    )

    (ip_dir / "DMA-STM32G081_dma1_v1_3_Modes.xml").write_text(
        textwrap.dedent("""\
            <?xml version="1.0"?>
            <IP xmlns="http://mcd.rou.st.com/modules.php?name=mcu"
                Name="DMA" Version="STM32G081_dma1_v1_3">
              <RefParameter Name="Request" Type="list">
                <PossibleValue Comment="MEMTOMEM"  Value="DMA_REQUEST_MEM2MEM"/>
                <PossibleValue Comment="ADC1"      Value="DMA_REQUEST_ADC1"/>
                <PossibleValue Comment="USART1_RX" Value="DMA_REQUEST_USART1_RX"/>
                <PossibleValue Comment="USART1_TX" Value="DMA_REQUEST_USART1_TX"/>
              </RefParameter>
            </IP>
        """),
        encoding="utf-8",
    )

    (clock_dir / "STM32G0.xml").write_text(
        textwrap.dedent("""\
            <?xml version="1.0"?>
            <Clock>
              <Tree id="ClockTree">
                <Element id="HSIRC" type="fixedSource">
                  <Output signalId="HSI" to="HSISYS"/>
                  <Output signalId="HSI" to="SysClkSource"/>
                </Element>
                <Element id="HSEOSC" type="variedSource">
                  <Output signalId="HSE" to="SysClkSource"/>
                </Element>
                <Element id="HSISYS" type="devisor">
                  <Input signalId="HSI" from="HSIRC"/>
                  <Output signalId="HSISYSCLK" to="SysClkSource"/>
                </Element>
                <Element id="SysClkSource" type="multiplexor">
                  <Input signalId="HSI" from="HSIRC"/>
                  <Input signalId="HSE" from="HSEOSC"/>
                  <Input signalId="HSISYSCLK" from="HSISYS"/>
                </Element>
              </Tree>
            </Clock>
        """),
        encoding="utf-8",
    )
    return db


# ---------------------------------------------------------------------------
# Pure-helper unit tests
# ---------------------------------------------------------------------------


def test_expand_variants_single_group() -> None:
    out = _expand_variants("STM32G071R(6-8-B)Tx")
    assert out == ("STM32G071R6Tx", "STM32G071R8Tx", "STM32G071RBTx")


def test_expand_variants_no_parens_passthrough() -> None:
    assert _expand_variants("STM32G071RBIx") == ("STM32G071RBIx",)


def test_expand_variants_multiple_groups_cross_product() -> None:
    out = _expand_variants("STM32H7(45-47)A(I-G)Hx")
    assert set(out) == {
        "STM32H745AIHx",
        "STM32H745AGHx",
        "STM32H747AIHx",
        "STM32H747AGHx",
    }


def test_canonical_pin_name_strips_alt_label() -> None:
    assert _canonical_pin_name("PA9 (PA9)") == "PA9"
    assert _canonical_pin_name("PC14-OSC32_IN (PC14)") == "PC14"
    assert _canonical_pin_name("PA10") == "PA10"


def test_canonical_pin_name_rejects_non_port_pin() -> None:
    assert _canonical_pin_name("VDD") is None
    assert _canonical_pin_name("VSS") is None
    assert _canonical_pin_name("") is None


# ---------------------------------------------------------------------------
# MCU XML / IP XML / clock-tree parsers
# ---------------------------------------------------------------------------


def test_match_mcu_xml_picks_variant_file_for_lowercase_device(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    matched = _match_mcu_xml(db / "mcu", "stm32g071rb")
    assert matched is not None
    assert matched.name == "STM32G071R(6-8-B)Tx.xml"


def test_match_mcu_xml_returns_none_when_no_match(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    assert _match_mcu_xml(db / "mcu", "stm32f407vg") is None


def test_parse_mcu_xml_collects_pins_and_versions(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    facts = _parse_mcu_xml(db / "mcu" / "STM32G071R(6-8-B)Tx.xml")
    assert facts.family == "STM32G0"
    assert facts.line == "STM32G0x1"
    assert facts.clock_tree == "STM32G0"
    assert facts.gpio_version == "STM32G07x_gpio_v1_0"
    assert facts.dma_versions == ("STM32G081_dma1_v1_3",)
    pin_names = {p.name for p in facts.pins}
    assert "PA9 (PA9)" in pin_names
    assert "PA10" in pin_names
    assert "VDD" in pin_names


def test_parse_gpio_ip_xml_extracts_af_rows(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    rows = _parse_gpio_ip_xml(
        db / "mcu" / "IP" / "GPIO-STM32G07x_gpio_v1_0_Modes.xml"
    )
    by_pin = {(r.pin, r.peripheral, r.signal): r.af_number for r in rows}
    assert by_pin[("PA9", "USART1", "TX")] == 1
    assert by_pin[("PA9", "I2C1", "SCL")] == 6
    assert by_pin[("PA10", "USART1", "RX")] == 1


def test_parse_dma_ip_xml_skips_nonperipheral_and_indexes_by_position(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    requests = _parse_dma_ip_xml(
        db / "mcu" / "IP" / "DMA-STM32G081_dma1_v1_3_Modes.xml"
    )
    by_signal = {(r.peripheral, r.signal): r for r in requests}
    # MEM2MEM is filtered.
    assert ("MEM2MEM", "") not in by_signal
    # Index reflects the XML position (verifies the deterministic
    # request_id projection).
    assert by_signal[("ADC1", "")].request_id == 1
    assert by_signal[("USART1", "RX")].request_id == 2
    assert by_signal[("USART1", "TX")].request_id == 3


def test_parse_clocktree_xml_collects_nodes_and_edges(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    nodes, edges = _parse_clocktree_xml(db / "plugins" / "clock" / "STM32G0.xml")
    node_kinds = {n.id: n.kind for n in nodes}
    assert node_kinds["HSIRC"] == "oscillator"
    assert node_kinds["HSEOSC"] == "oscillator"
    assert node_kinds["HSISYS"] == "divider"
    assert node_kinds["SysClkSource"] == "selector"
    edge_pairs = {(e.source, e.target) for e in edges}
    assert ("HSIRC", "HSISYS") in edge_pairs
    assert ("HSIRC", "SysClkSource") in edge_pairs
    assert ("HSEOSC", "SysClkSource") in edge_pairs


# ---------------------------------------------------------------------------
# End-to-end via the registered extractor
# ---------------------------------------------------------------------------


def test_extractor_payload_carries_pins_dma_clocks(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    ext = resolve_extractor_by_id("stm32-cubemx")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"stm32cubemx-db": db},
        revision="cubemx-v6.17",
    )
    result = ext.extract(request)
    payload = result.payload

    # Identity / provenance.
    assert payload["provenance"]["source_id"] == "stm32-cubemx"
    assert "stm32-cubemx@cubemx-v6.17" in payload["provenance"]["patch_ids"]
    assert payload["identity"]["device"] == "stm32g071rb"

    # Pins: AF-bearing pins carry canonical PinSignal rows
    # (function/peripheral/signal/af_number/provenance); pinout-
    # only pins (PC14) still appear with an empty signals tuple.
    pins_by_name = {p["name"]: p for p in payload["pins"]}
    pa9_signals = list(pins_by_name["PA9"]["signals"])
    pa9_pairs = {(s["af_number"], s["peripheral"], s["signal"]) for s in pa9_signals}
    assert (1, "USART1", "TX") in pa9_pairs
    assert pins_by_name["PA9"]["port"] == "A"
    assert pins_by_name["PA9"]["number"] == 9
    assert pins_by_name["PA10"]["signals"][0]["signal"] == "RX"
    assert pins_by_name["PC14"]["signals"] == ()

    # DMA: canonical DmaRequestDefinition shape.
    dma = payload["dma_requests"]
    by_signal = {(d["peripheral"], d["signal"]): d for d in dma}
    assert by_signal[("USART1", "TX")]["request_value"] == 3
    assert by_signal[("USART1", "TX")]["request_line"] == "DMA_REQUEST_USART1_TX"
    assert by_signal[("USART1", "TX")]["controller"] == "DMAMUX"

    # Clock tree: nodes + selector for SysClkSource (canonical
    # ClockNodeLite shape: node_id / kind / parent / selector /
    # provenance).
    nodes_by_id = {n["node_id"]: n for n in payload["clock_nodes"]}
    assert nodes_by_id["HSIRC"]["kind"] == "oscillator"
    selectors_by_id = {s["selector_id"]: s for s in payload["clock_selectors"]}
    assert "SysClkSource" in selectors_by_id
    assert set(selectors_by_id["SysClkSource"]["parent_options"]) == {
        "HSIRC",
        "HSEOSC",
        "HSISYS",
    }


def test_extractor_raises_missing_source_when_path_absent() -> None:
    ext = resolve_extractor_by_id("stm32-cubemx")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={},
        revision="r",
    )
    with pytest.raises(MissingSourceError) as excinfo:
        ext.extract(request)
    assert "stm32cubemx-db" in str(excinfo.value)


def test_extractor_raises_value_error_when_device_unknown(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    ext = resolve_extractor_by_id("stm32-cubemx")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g999zz",
        source_paths={"stm32cubemx-db": db},
        revision="r",
    )
    with pytest.raises(ValueError, match="no MCU XML"):
        ext.extract(request)


def test_extractor_does_not_win_resolver_for_st_family() -> None:
    """`stm32-cubemx` is secondary — must not auto-resolve for ST."""
    ext = resolve_extractor("st", "stm32g0")
    assert ext.extractor_id == "stm32"


# ---------------------------------------------------------------------------
# Real-DB smoke tests across F0 / F4 / G0 — opt-in (skipped when
# STM32CubeMX is not installed at the default macOS path).
# ---------------------------------------------------------------------------


_DEFAULT_CUBEMX_DB = Path(
    "/Applications/STMicroelectronics/STM32CubeMX.app/Contents/Resources/db"
)


@pytest.mark.parametrize(
    ("device", "family", "min_pins", "expect_clock_tree"),
    [
        ("stm32f071rb", "stm32f0", 30, True),
        ("stm32f407vg", "stm32f4", 60, True),
        ("stm32g071rb", "stm32g0", 30, True),
    ],
)
def test_extract_against_real_cubemx_db(
    device: str, family: str, min_pins: int, expect_clock_tree: bool
) -> None:
    if not _DEFAULT_CUBEMX_DB.exists():
        pytest.skip(f"STM32CubeMX not installed at {_DEFAULT_CUBEMX_DB}")
    ext = resolve_extractor_by_id("stm32-cubemx")
    request = ExtractionRequest(
        vendor="st",
        family=family,
        device=device,
        source_paths={"stm32cubemx-db": _DEFAULT_CUBEMX_DB},
        revision="local-cubemx",
    )
    payload = ext.extract(request).payload
    assert payload["identity"]["device"] == device
    assert len(payload["pins"]) >= min_pins
    # At least one pin carries a USART AF entry on each of these.
    has_usart_af = any(
        any(
            (af.get("peripheral") or "").startswith("USART")
            for af in pin["signals"]
        )
        for pin in payload["pins"]
    )
    assert has_usart_af, f"no USART AF surfaced for {device}"
    if expect_clock_tree:
        assert payload["clock_nodes"], (
            f"no clock-tree nodes parsed for {device}"
        )
