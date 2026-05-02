"""Tests for the STM32 tier-2/3/4 → v2.1 extractor."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.extractors.stm32_tier_v2_1 import (  # noqa: E402
    _resolve_template_id,
    extract_device,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip_name,expected",
    [
        ("TIM1_8G0", "timer_advanced"),
        ("gptimer1_v2_x_Cube", "timer_general"),
        ("USART", "usart"),
        ("SPI", "spi"),
        ("I2C", "i2c"),
        ("ADC", "adc"),
        ("GPIO", "gpio"),
        ("UART", "uart"),
    ],
)
def test_resolve_template_id(ip_name: str, expected: str) -> None:
    assert _resolve_template_id(ip_name) == expected


# ---------------------------------------------------------------------------
# Real extractor — uses the open-pin-data XML when available
# ---------------------------------------------------------------------------


_OPEN_PIN_DIR = (
    ROOT.parent
    / "alloy-codegen"
    / ".cache"
    / "sources"
    / "STM32_open_pin_data"
    / "mcu"
)


def _have_xml(name: str) -> Path:
    path = _OPEN_PIN_DIR / name
    if not path.is_file():
        pytest.skip(f"Open-pin-data XML {name} not present.")
    return path


def test_extract_device_emits_v2_1_payload() -> None:
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    assert payload["schema"] == "alloy.device.v2.1"
    assert payload["provenance"]["primary"].startswith("stm32-tier:")


def test_extract_device_emits_timer_trigger_sources() -> None:
    """Delta 6 — TIM1 SMCR.TS field-value mapping."""
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    advanced = payload["templates"].get("timer_advanced") or {}
    triggers = advanced.get("trigger_sources") or {}
    assert "itr0" in triggers and triggers["itr0"] == 0
    assert "etrf" in triggers
    # All trigger source values are 0..7 (3-bit field).
    assert all(0 <= v <= 7 for v in triggers.values())


def test_extract_device_emits_timer_master_outputs() -> None:
    """Delta 7 — TIM1 CR2.MMS field-value mapping."""
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    advanced = payload["templates"].get("timer_advanced") or {}
    masters = advanced.get("master_outputs") or {}
    assert "reset" in masters and masters["reset"] == 0
    assert "enable" in masters and masters["enable"] == 1
    assert "update" in masters and masters["update"] == 2


def test_extract_device_emits_pwm_break_inputs_and_deadtime() -> None:
    """Delta 8 — advanced timer break-input + DTG options."""
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    advanced = payload["templates"].get("timer_advanced") or {}
    breaks = advanced.get("break_inputs") or []
    assert "bkin" in breaks
    deadtime = advanced.get("deadtime_options") or []
    assert len(deadtime) >= 1
    assert "dtg_prescaler" in deadtime[0]
    assert "count_bits" in deadtime[0]
    assert "max_ns" in deadtime[0]


def test_extract_device_emits_uart_data_bits_encoding() -> None:
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    usart = payload["templates"].get("usart") or {}
    options = usart.get("options") or {}
    assert "data_bits" in options
    assert 8 in options["data_bits"]
    # The encoding map keys are spelled "8bit" / "9bit" / "7bit".
    enc = options.get("data_bits_encoding") or {}
    assert "8bit" in enc


def test_extract_device_emits_spi_baud_prescaler() -> None:
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    spi = payload["templates"].get("spi") or {}
    options = spi.get("options") or {}
    bp = options.get("baud_prescaler") or []
    # SPI baud_prescaler list: div_2, div_4, …, div_256.
    assert "div_2" in bp
    assert "div_256" in bp
    enc = options.get("baud_prescaler_encoding") or {}
    assert enc.get("div_2") == 0
    assert enc.get("div_256") == 7


def test_extract_device_emits_i2c_speed_options() -> None:
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    i2c = payload["templates"].get("i2c") or {}
    speeds = (i2c.get("options") or {}).get("speeds") or []
    assert "100kHz" in speeds and "400kHz" in speeds


def test_extract_device_emits_adc_external_triggers_per_instance() -> None:
    """Delta 4 — ADC1.external_triggers maps timer events to EXTSEL."""
    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    adc = next((p for p in payload["peripherals"]
                if p.get("template") == "adc"), None)
    assert adc is not None
    triggers = adc.get("external_triggers") or {}
    assert "regular" in triggers
    regular = triggers["regular"]
    assert len(regular) >= 4
    for row in regular:
        assert "source" in row
        assert "extsel" in row


def test_extract_device_validates_via_v2_1_reader() -> None:
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    xml = _have_xml("STM32G030F6Px.xml")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        open_pin_data_xml=xml,
    )
    device = parse_device_payload(payload)
    assert device.schema == "alloy.device.v2.1"


# ---------------------------------------------------------------------------
# 4-source full stack — SVD primary + open-pin-data + overlay + tier
# ---------------------------------------------------------------------------


def test_full_stack_merge_carries_every_delta() -> None:
    """End-to-end: every covered delta of the audit lands on the
    final IR — calibration ROM, ip_version, max_clock_override,
    timer trigger_sources / master_outputs, PWM break_inputs +
    deadtime, ADC external_triggers."""
    xml = _have_xml("STM32G030F6Px.xml")
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    from alloy_data_extractor.extractors.cmsis_svd_v2_1 import (
        extract_device as svd_extract,
    )
    from alloy_data_extractor.extractors.stm32_open_pin_data_v2_1 import (
        extract_device as opd_extract,
    )
    from alloy_data_extractor.extractors.stm32_overlay_v2_1 import (
        extract_device as overlay_extract,
    )
    from alloy_data_extractor.merge_v2_1 import STM32_MERGE_POLICY, merge_payloads

    svd = (ROOT.parent / "alloy-codegen" / ".cache" / "sources"
           / "cmsis-svd-data" / "data" / "STMicro" / "STM32G030.svd")
    if not svd.is_file():
        pytest.skip("STM32G030.svd not present")

    overlay_root = ROOT / "data"
    if not (overlay_root / "vendors" / "st" / "stm32g0" / "family.toml").is_file():
        pytest.skip("STM32G0 overlay not present")

    primary = svd_extract(vendor="st", family="stm32g0",
                           device="stm32g030f6", svd_path=svd)
    e1 = opd_extract(vendor="st", family="stm32g0",
                      device="stm32g030f6", xml_path=xml)
    e2 = overlay_extract(vendor="st", family="stm32g0",
                          device="stm32g030f6", overlay_root=overlay_root)
    e3 = extract_device(vendor="st", family="stm32g0",
                         device="stm32g030f6", open_pin_data_xml=xml)
    result = merge_payloads(primary=primary, enrichments=(e1, e2, e3),
                             policy=STM32_MERGE_POLICY)
    device = parse_device_payload(result.payload)

    # Calibration ROM (overlay).
    adc = next(p for p in device.peripherals if p.template == "adc")
    assert adc.calibration is not None
    assert adc.calibration.vrefint.rom_addr == 0x1FFF75AA

    # Timer trigger_sources (tier).
    advanced = device.templates.get("timer_advanced")
    assert advanced is not None
    assert advanced.trigger_sources.get("itr0") == 0
    assert advanced.master_outputs.get("update") == 2

    # PWM break + deadtime (tier).
    assert "bkin" in advanced.break_inputs

    # ADC external triggers (tier, per-instance).
    assert len(adc.external_triggers.get("regular", ())) >= 1
    assert all(t.extsel is not None
               for t in adc.external_triggers["regular"])

    # ip_version (open-pin-data).
    assert adc.ip_version == "aditf4_v3_0_G0_Cube"

    # All four sources contributed.
    assert "stm32-open-pin-data:STM32G030F6Px.xml" in device.provenance.secondary
    assert "stm32-overlay:stm32g0" in device.provenance.secondary
    assert "stm32-tier:stm32g030f6" in device.provenance.secondary
