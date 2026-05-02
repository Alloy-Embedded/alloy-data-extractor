"""Tests for the STM32 hand-curated overlay → v2.1 extractor."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.extractors.stm32_overlay_v2_1 import (  # noqa: E402
    _bytes_with_unit,
    _hz_with_unit,
    extract_device,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (1024, "1KB"), (32768, "32KB"), (524288, "512KB"),
        (147456, "144KB"), (2 << 20, "2MB"), (1 << 30, "1GB"),
        (1, "1B"),
    ],
)
def test_bytes_with_unit(raw: int, expected: str) -> None:
    assert _bytes_with_unit(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (16_000_000, "16MHz"), (35_000_000, "35MHz"),
        (1_000_000, "1MHz"), (32_768, "32768Hz"),
    ],
)
def test_hz_with_unit(raw: int, expected: str) -> None:
    assert _hz_with_unit(raw) == expected


# ---------------------------------------------------------------------------
# extract_device on the real STM32G0 family overlay
# ---------------------------------------------------------------------------


_OVERLAY_ROOT = ROOT / "data"


def _have_family_overlay() -> Path:
    family_toml = _OVERLAY_ROOT / "vendors" / "st" / "stm32g0" / "family.toml"
    if not family_toml.is_file():
        pytest.skip(f"Family overlay not present: {family_toml}")
    return family_toml


def test_extract_device_emits_v2_1_payload() -> None:
    _have_family_overlay()
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    assert payload["schema"] == "alloy.device.v2.1"
    assert payload["provenance"]["primary"].startswith("stm32-overlay:")
    assert payload["provenance"]["authored"] == "hand"


def test_extract_device_carries_memory_with_aliases() -> None:
    _have_family_overlay()
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    by_id = {m["id"]: m for m in payload["memory"]}
    assert "flash" in by_id and by_id["flash"]["alias"] == "code"
    assert "sram" in by_id and by_id["sram"]["alias"] == "data"
    # FLASH base = 0x08000000 on STM32G0.
    assert by_id["flash"]["base"] == "0x8000000"


def test_extract_device_carries_clock_profiles() -> None:
    _have_family_overlay()
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    profile_ids = {p["id"] for p in payload["clock"]["profiles"]}
    assert "default-hsi16-16mhz" in profile_ids
    assert "pll-hsi16-64mhz" in profile_ids


def test_extract_device_emits_adc_calibration_block() -> None:
    _have_family_overlay()
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    # Both 'adc' and 'adc1' rows are emitted — merge engine drops phantom.
    adc_rows = [p for p in payload["peripherals"]
                if p.get("id") in {"adc", "adc1"} and "calibration" in p]
    assert len(adc_rows) == 2
    cal = adc_rows[0]["calibration"]
    assert cal["vrefint"]["rom_addr"] == "0x1FFF75AA"
    assert cal["vrefint"]["nominal_mv"] == 3000
    assert cal["ts_cal_low"]["rom_addr"] == "0x1FFF75A8"
    assert cal["ts_cal_low"]["temp_celsius"] == 30
    assert cal["ts_cal_high"]["rom_addr"] == "0x1FFF75CA"
    assert cal["ts_cal_high"]["temp_celsius"] == 130


def test_extract_device_emits_adc_internal_channels() -> None:
    _have_family_overlay()
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    adc = next(p for p in payload["peripherals"]
               if p.get("id") == "adc" and "channels" in p)
    assert adc["channels"] == {
        "ch13": "vrefint",
        "ch12": "temperature_sensor",
        "ch14": "vbat",
    }


def test_extract_device_emits_template_max_clocks() -> None:
    _have_family_overlay()
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    templates = payload.get("templates") or {}
    assert templates.get("adc", {}).get("max_clock") == "35MHz"
    assert templates.get("i2c", {}).get("max_clock") == "1MHz"
    assert templates.get("usart", {}).get("max_baud") == 4_000_000


def test_extract_device_validates_via_v2_1_reader() -> None:
    """The overlay enrichment must be parse_device_payload-clean."""
    _have_family_overlay()
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g030f6",
        overlay_root=_OVERLAY_ROOT,
    )
    device = parse_device_payload(payload)
    assert device.schema == "alloy.device.v2.1"


def test_f4_overlay_carries_different_calibration_addresses() -> None:
    f4_toml = _OVERLAY_ROOT / "vendors" / "st" / "stm32f4" / "family.toml"
    if not f4_toml.is_file():
        pytest.skip("F4 overlay not present")
    payload = extract_device(
        vendor="st", family="stm32f4", device="stm32f401re",
        overlay_root=_OVERLAY_ROOT,
    )
    adc = next(p for p in payload["peripherals"]
               if p.get("id") == "adc1" and "calibration" in p)
    cal = adc["calibration"]
    # F4 family has TS_CAL1 at 0x1FFF7A2C (different from G0).
    assert cal["ts_cal_low"]["rom_addr"] == "0x1FFF7A2C"
    assert cal["ts_cal_low"]["temp_celsius"] == 30
    # F4 cal voltage = 3300 mV (G0 uses 3000 mV).
    assert cal["vrefint"]["nominal_mv"] == 3300


def test_extract_device_unknown_family_raises() -> None:
    with pytest.raises(FileNotFoundError):
        extract_device(
            vendor="st", family="stm32xx-unknown",
            device="stm32xx", overlay_root=_OVERLAY_ROOT,
        )


# ---------------------------------------------------------------------------
# End-to-end with merge engine — the real value-add
# ---------------------------------------------------------------------------


def test_overlay_merges_with_svd_primary() -> None:
    """SVD primary + overlay enrichment → ADC carries calibration ROM."""
    _have_family_overlay()
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    from alloy_data_extractor.extractors.cmsis_svd_v2_1 import (
        extract_device as svd_extract,
    )
    from alloy_data_extractor.merge_v2_1 import STM32_MERGE_POLICY, merge_payloads

    svd = (ROOT.parent / "alloy-codegen" / ".cache" / "sources"
           / "cmsis-svd-data" / "data" / "STMicro" / "STM32G030.svd")
    if not svd.is_file():
        pytest.skip("STM32G030.svd not present (cmsis-svd-data not checked out)")

    primary = svd_extract(vendor="st", family="stm32g0",
                          device="stm32g030f6", svd_path=svd)
    overlay = extract_device(vendor="st", family="stm32g0",
                              device="stm32g030f6", overlay_root=_OVERLAY_ROOT)
    result = merge_payloads(primary=primary, enrichments=(overlay,),
                            policy=STM32_MERGE_POLICY)
    device = parse_device_payload(result.payload)

    # ADC peripheral now carries the overlay's calibration block.
    adc = next(p for p in device.peripherals if p.template == "adc")
    assert adc.calibration is not None
    assert adc.calibration.vrefint is not None
    assert adc.calibration.vrefint.rom_addr == 0x1FFF75AA
    assert adc.max_clock_override == "35MHz"

    # Memory was promoted from the overlay (replacing SVD's placeholder).
    by_id = {m.id: m for m in device.memory}
    assert "flash" in by_id and by_id["flash"].size == "512KB"
    assert "sram" in by_id and by_id["sram"].size == "144KB"

    # Clock profiles arrived from overlay.
    profile_ids = {p.id for p in device.clock.profiles}
    assert "default-hsi16-16mhz" in profile_ids
    assert "pll-hsi16-64mhz" in profile_ids
