"""Tests for the STM32 open-pin-data extractor.

Synthetic-XML focused unit tests + a fixture-backed end-to-end
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

import alloy_data_extractor.pipeline  # noqa: E402,F401
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor_by_id,
)
from alloy_data_extractor.extractors.stm32_open_pin_data import (  # noqa: E402
    parse_pin_data_document,
)


def _write_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Write a synthetic STM32 MCU XML + matching GPIO modes XML.

    Mirrors the structure ST publishes in STM32_open_pin_data so
    the parser exercises every code path: GPIO IP version,
    Pin / Signal / SpecificParameter rows, package pads.
    """
    mcu = tmp_path / "STM32SYNTHRB.xml"
    mcu.write_text(
        textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <Mcu xmlns="http://dummy.com" RefName="STM32SYNTHRB" Package="LQFP64">
              <IP Name="GPIO" Version="STM32G0_gpio_v1_0" InstanceName="GPIO"/>
              <Pin Name="VBAT" Position="1" Type="Power" />
              <Pin Name="PA9" Position="42" Type="I/O">
                <Signal Name="USART1_TX" />
                <Signal Name="GPIO" />
              </Pin>
              <Pin Name="PA10" Position="43" Type="I/O">
                <Signal Name="USART1_RX" />
              </Pin>
              <Pin Name="NRST" Position="7" Type="Reset" />
              <Pin Name="NC" Position="64" Type="NC" />
            </Mcu>
        """),
        encoding="utf-8",
    )
    gpio = tmp_path / "GPIO-STM32G0_gpio_v1_0_Modes.xml"
    gpio.write_text(
        textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <IP xmlns="http://dummy.com">
              <GPIO_Pin Name="PA9">
                <PinSignal Name="USART1_TX">
                  <SpecificParameter Name="GPIO_AF">
                    <PossibleValue>GPIO_AF1_USART1</PossibleValue>
                  </SpecificParameter>
                </PinSignal>
              </GPIO_Pin>
              <GPIO_Pin Name="PA10">
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
    return mcu, gpio


def test_parser_resolves_pa9_pa10_alternate_functions(tmp_path: Path) -> None:
    mcu, gpio = _write_pair(tmp_path)
    doc = parse_pin_data_document(mcu_path=mcu, gpio_modes_path=gpio)
    pins = {p.name: p for p in doc.pins}
    assert "PA9" in pins
    assert pins["PA9"].port == "A"
    assert pins["PA9"].number == 9
    assert any(s.signal_name == "USART1_TX" and s.af_number == 1 for s in pins["PA9"].signals)
    assert any(s.signal_name == "USART1_RX" and s.af_number == 1 for s in pins["PA10"].signals)


def test_parser_classifies_package_pads(tmp_path: Path) -> None:
    mcu, gpio = _write_pair(tmp_path)
    doc = parse_pin_data_document(mcu_path=mcu, gpio_modes_path=gpio)
    pads = {p.position_label: p for p in doc.package_pads}
    # VBAT at position 1 is a power pad — not bonded to a GPIO.
    assert pads["1"].pad_kind == "power"
    assert pads["1"].bonded_pin is None
    # NRST at position 7 is a reset pad.
    assert pads["7"].pad_kind == "reset"
    # NC at position 64 is unbonded.
    assert pads["64"].pad_kind == "nc"
    assert pads["64"].bonding_state == "unbonded"
    # PA9 at position 42 is a bonded I/O pad.
    assert pads["42"].pad_kind == "io"
    assert pads["42"].bonded_pin == "PA9"
    assert pads["42"].bonding_state == "bonded"


def test_parser_extracts_package_pin_count(tmp_path: Path) -> None:
    mcu, gpio = _write_pair(tmp_path)
    doc = parse_pin_data_document(mcu_path=mcu, gpio_modes_path=gpio)
    assert doc.package_name == "lqfp64"
    assert doc.package_pin_count == 64


def test_extractor_resolves_via_id() -> None:
    ext = resolve_extractor_by_id("stm32-open-pin-data")
    assert ext.extractor_id == "stm32-open-pin-data"


def test_extractor_payload_round_trip(tmp_path: Path) -> None:
    mcu, gpio = _write_pair(tmp_path)
    ext = resolve_extractor_by_id("stm32-open-pin-data")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32synthrb",
        source_paths={
            "stm32-open-pin-data-mcu": mcu,
            "stm32-open-pin-data-gpio": gpio,
        },
        revision="opd-test",
    )
    result = ext.extract(request)
    assert result.payload["provenance"]["source_id"] == "stm32-open-pin-data"
    pa9 = next(p for p in result.payload["pins"] if p["name"] == "PA9")
    assert pa9["alternate_functions"] == [
        {"af": 1, "signal": "USART1_TX", "peripheral": "USART1"}
    ]
    pads = result.payload["package_pads"]
    assert any(p["pad_id"] == "1" and p["pad_kind"] == "power" for p in pads)


def test_extractor_resolves_paths_from_repo_root(tmp_path: Path) -> None:
    """When given a repo root, the extractor walks ``mcu/`` for
    the device's MCU XML and resolves the GPIO modes file from
    the IP version embedded in it."""
    root = tmp_path / "stm32-open-pin-data"
    (root / "mcu").mkdir(parents=True)
    (root / "mcu" / "IP").mkdir()
    mcu, gpio = _write_pair(root / "mcu" / "IP")  # writes both into IP/
    # Move mcu to mcu/ root (not under IP/) for the walking logic.
    target_mcu = root / "mcu" / "STM32SYNTHRB.xml"
    target_mcu.write_text(mcu.read_text(encoding="utf-8"), encoding="utf-8")
    target_gpio = root / "mcu" / "IP" / "GPIO-STM32G0_gpio_v1_0_Modes.xml"
    target_gpio.write_text(gpio.read_text(encoding="utf-8"), encoding="utf-8")

    ext = resolve_extractor_by_id("stm32-open-pin-data")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32synthrb",
        source_paths={"stm32-open-pin-data": root},
        revision="repo-root",
    )
    result = ext.extract(request)
    pin_names = {p["name"] for p in result.payload["pins"]}
    assert {"PA9", "PA10"}.issubset(pin_names)


def test_extractor_raises_when_paths_missing() -> None:
    ext = resolve_extractor_by_id("stm32-open-pin-data")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32synthrb",
        source_paths={},
        revision="r",
    )
    with pytest.raises(ValueError, match="stm32-open-pin-data"):
        ext.extract(request)


def test_extractor_does_not_win_resolver_for_st_family() -> None:
    """stm32-open-pin-data is secondary — must not auto-resolve."""
    from alloy_data_extractor.extractor_protocol import resolve_extractor

    assert resolve_extractor("st", "stm32g0").extractor_id == "stm32"


def test_resolve_paths_returns_none_when_modes_file_missing(tmp_path: Path) -> None:
    """If the MCU XML names a GPIO version whose Modes file isn't
    on disk, the extractor surfaces a clear ValueError (not a
    crash)."""
    root = tmp_path / "stm32-open-pin-data"
    (root / "mcu" / "IP").mkdir(parents=True)
    (root / "mcu" / "STM32SYNTH.xml").write_text(
        '<?xml version="1.0"?><Mcu xmlns="http://dummy.com" RefName="STM32SYNTH" Package="LQFP32">'
        '<IP Name="GPIO" Version="vMissing"/></Mcu>',
        encoding="utf-8",
    )

    ext = resolve_extractor_by_id("stm32-open-pin-data")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32synth",
        source_paths={"stm32-open-pin-data": root},
        revision="r",
    )
    with pytest.raises(ValueError, match="stm32-open-pin-data"):
        ext.extract(request)
