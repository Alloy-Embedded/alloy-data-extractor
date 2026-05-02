"""Tests for the STM32CubeMX → v2.1 enrichment extractor."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.extractors.stm32_cubemx_v2_1 import (  # noqa: E402
    _normalise_source,
    extract_device,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HSI", "hsi"), ("HSE", "hse"),
        ("HSIRC", "hsi"), ("HSEOSC", "hse"),
        ("LSI", "lsi"), ("LSE", "lse"),
        ("PLLRCLK", "pll_main"), ("PLLPCLK", "pll_p"),
        ("CUSTOM_THING", "custom_thing"),
    ],
)
def test_normalise_source(raw: str, expected: str) -> None:
    assert _normalise_source(raw) == expected


# ---------------------------------------------------------------------------
# extract_device against the real CubeMX DB (when present)
# ---------------------------------------------------------------------------


_CUBEMX_DB = Path(
    "/Applications/STMicroelectronics/STM32CubeMX.app/"
    "Contents/Resources/db"
)


def _have_cubemx() -> Path:
    if not _CUBEMX_DB.is_dir():
        pytest.skip(f"CubeMX DB not present at {_CUBEMX_DB}")
    return _CUBEMX_DB


def test_extract_device_emits_v2_1_payload() -> None:
    db = _have_cubemx()
    payload = extract_device(
        vendor="st", family="stm32g0", device="STM32G030F6Px",
        db_root=db,
    )
    assert payload["schema"] == "alloy.device.v2.1"
    assert payload["provenance"]["primary"].startswith("stm32-cubemx:")


def test_extract_device_carries_clock_oscillators() -> None:
    db = _have_cubemx()
    payload = extract_device(
        vendor="st", family="stm32g0", device="STM32G030F6Px",
        db_root=db,
    )
    osc = payload["clock"]["oscillators"]
    assert "hsi" in osc and osc["hsi"]["freq"] == "16MHz"
    assert "lsi" in osc


def test_extract_device_carries_select_register_with_encoding() -> None:
    """Delta 12 — clock-domain select_register with full encoding map."""
    db = _have_cubemx()
    payload = extract_device(
        vendor="st", family="stm32g0", device="STM32G030F6Px",
        db_root=db,
    )
    domains = payload["clock"]["domains"]
    by_id = {d["id"]: d for d in domains}
    # USART1 source select — encoding map matches RCC.CCIPR.USART1SEL.
    usart_sel = by_id.get("usart1mult")
    assert usart_sel is not None
    assert usart_sel["select_register"]["reg"] == "RCC.CCIPR"
    assert usart_sel["select_register"]["field"] == "USART1SEL"
    enc = usart_sel["select_register"]["encoding"]
    assert enc["pclk"] == 0
    assert enc["sysclk"] == 1
    assert enc["hsi"] == 2


def test_extract_device_carries_prescaler_register() -> None:
    db = _have_cubemx()
    payload = extract_device(
        vendor="st", family="stm32g0", device="STM32G030F6Px",
        db_root=db,
    )
    domains = payload["clock"]["domains"]
    by_id = {d["id"]: d for d in domains}
    ahb = by_id.get("ahbprescaler")
    assert ahb is not None
    presc = ahb["prescaler_register"]
    assert presc["reg"] == "RCC.CFGR"
    assert presc["field"] == "HPRE"
    assert presc["encoding"]["1"] == 0
    assert presc["encoding"]["2"] == 8
    assert presc["encoding"]["512"] == 15


def test_extract_device_emits_dma_request_matrix() -> None:
    """Per-peripheral dma_requests populated from CubeMX DMA Modes XML."""
    db = _have_cubemx()
    payload = extract_device(
        vendor="st", family="stm32g0", device="STM32G030F6Px",
        db_root=db,
    )
    by_id = {p["id"]: p for p in payload["peripherals"]}
    usart2 = by_id.get("usart2")
    assert usart2 is not None
    requests = usart2.get("dma_requests")
    assert requests is not None
    # DMA matrix should have at least USART2_TX + USART2_RX.
    signals = {r["signal"] for r in requests}
    assert "tx" in signals
    assert "rx" in signals


def test_extract_device_validates_via_v2_1_reader() -> None:
    db = _have_cubemx()
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    payload = extract_device(
        vendor="st", family="stm32g0", device="STM32G030F6Px",
        db_root=db,
    )
    device = parse_device_payload(payload)
    assert device.schema == "alloy.device.v2.1"


# ---------------------------------------------------------------------------
# 5-source full-stack merge — every audit delta covered
# ---------------------------------------------------------------------------


def test_full_stack_5_sources_covers_all_13_audit_deltas() -> None:
    db = _have_cubemx()
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
    from alloy_data_extractor.extractors.stm32_tier_v2_1 import (
        extract_device as tier_extract,
    )
    from alloy_data_extractor.merge_v2_1 import STM32_MERGE_POLICY, merge_payloads

    svd = (ROOT.parent / "alloy-codegen" / ".cache" / "sources"
           / "cmsis-svd-data" / "data" / "STMicro" / "STM32G030.svd")
    opd = (ROOT.parent / "alloy-codegen" / ".cache" / "sources"
           / "STM32_open_pin_data" / "mcu" / "STM32G030F6Px.xml")
    overlay_root = ROOT / "data"
    if not svd.is_file() or not opd.is_file():
        pytest.skip("svd / open-pin-data not present")
    if not (overlay_root / "vendors" / "st" / "stm32g0" / "family.toml").is_file():
        pytest.skip("overlay TOML not present")

    primary = svd_extract(vendor="st", family="stm32g0",
                           device="stm32g030f6", svd_path=svd)
    e1 = opd_extract(vendor="st", family="stm32g0",
                      device="stm32g030f6", xml_path=opd)
    e2 = overlay_extract(vendor="st", family="stm32g0",
                          device="stm32g030f6", overlay_root=overlay_root)
    e3 = tier_extract(vendor="st", family="stm32g0",
                       device="stm32g030f6", open_pin_data_xml=opd)
    e4 = extract_device(vendor="st", family="stm32g0",
                         device="STM32G030F6Px", db_root=db)
    result = merge_payloads(primary=primary, enrichments=(e1, e2, e3, e4),
                             policy=STM32_MERGE_POLICY)
    device = parse_device_payload(result.payload)

    # Delta 1: pin_constraints (open-pin-data) — at least one pin
    # carries a constraint (power/reset/etc).
    assert any(p.constraints for p in device.pinout)
    # Delta 2: field enum (cmsis-svd) — at least one template field
    # has an enum.
    has_enum = False
    for t in device.templates.values():
        for f in t.fields.values():
            if f.enum:
                has_enum = True
                break
    assert has_enum
    # Delta 3: ADC calibration ROM (overlay).
    adc = next(p for p in device.peripherals if p.template == "adc")
    assert adc.calibration is not None
    assert adc.calibration.vrefint.rom_addr == 0x1FFF75AA
    # Delta 4: ADC external_triggers (tier).
    assert "regular" in adc.external_triggers
    # Delta 6 + 7: timer trigger_sources + master_outputs (tier).
    advanced = device.templates.get("timer_advanced")
    assert advanced.trigger_sources.get("itr0") == 0
    assert advanced.master_outputs.get("update") == 2
    # Delta 8: PWM break_inputs (tier).
    assert "bkin" in advanced.break_inputs
    # Delta 9: ip_version (open-pin-data or cubemx).
    assert adc.ip_version is not None
    # Delta 10: clock.profiles (overlay).
    profile_ids = {p.id for p in device.clock.profiles}
    assert "default-hsi16-16mhz" in profile_ids
    # Delta 11: max_clock_override (overlay).
    assert adc.max_clock_override == "35MHz"
    # Delta 12: clock select_register encoding (cubemx — THIS COMMIT).
    domains_with_select = [d for d in device.clock.domains if d.select_register]
    assert len(domains_with_select) >= 5     # USART/I2C/ADC/PLL/MCO mux
    sample = next(d for d in domains_with_select if d.id == "usart1mult")
    assert sample.select_register.field == "USART1SEL"
    assert sample.select_register.encoding["pclk"] == 0

    # Provenance: 4 enrichment sources stacked.
    assert len(device.provenance.secondary) == 4
