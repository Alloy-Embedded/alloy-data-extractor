"""Tests for the v2.1 merge engine."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.merge_v2_1 import (  # noqa: E402
    MergePolicy,
    STM32_MERGE_POLICY,
    merge_payloads,
)


# ---------------------------------------------------------------------------
# Minimum-viable v2.1 primary (from cmsis-svd)
# ---------------------------------------------------------------------------


def _svd_primary() -> dict:
    return {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": "st", "family": "stm32g0", "device": "stm32g030f6",
            "core": {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
        },
        "provenance": {"primary": "cmsis-svd:STM32G030.svd", "authored": "auto"},
        "memory": [
            {"id": "flash", "base": "0x08000000", "size": "32KB", "access": "rx"},
            {"id": "sram",  "base": "0x20000000", "size": "8KB",  "access": "rw"},
        ],
        "clock": {
            "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
            "domains":     [{"id": "sysclk", "sources": ["unknown"]}],
        },
        "templates": {
            "adc": {
                "registers": {"cr": {"offset": 0}},
                "fields":    {"cr.aden": {"bit": 0}},
            },
            "usart": {
                "registers": {"cr1": {"offset": 0}},
                "fields":    {"cr1.ue": {"bit": 0}},
            },
        },
        "peripherals": [
            {"id": "adc1",   "template": "adc",   "base": "0x40012400"},
            {"id": "usart2", "template": "usart", "base": "0x40004400"},
        ],
        "pinout":     [{"signal": "RESET"}],   # placeholder
        "interrupts": [{"num": 28, "name": "USART2_IRQHandler"}],
    }


def _open_pin_data_enrichment() -> dict:
    """Enrichment from stm32-open-pin-data — fills pinout + per-peripheral pin_options."""
    return {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": "st", "family": "stm32g0", "device": "stm32g030f6",
            "core": {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
        },
        "provenance": {"primary": "stm32-open-pin-data", "authored": "auto"},
        "memory": [],
        "clock": {
            "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
            "domains": [{"id": "sysclk", "sources": ["unknown"]}],
        },
        "peripherals": [
            {
                "id": "usart2",
                "template": "usart",
                "pin_options": {
                    "tx": [{"pin": "PA2"}, {"pin": "PA14"}],
                    "rx": [{"pin": "PA3"}, {"pin": "PA15"}],
                },
            },
        ],
        "pinout": [
            {"pin": 1, "signal": "VBAT"},
            {"pin": 7, "signal": "PA0"},
            {"pin": 8, "signal": "PA1"},
            {"pin": 9, "signal": "PA2"},
        ],
    }


def _overlay_enrichment() -> dict:
    """Enrichment from stm32-overlay — ADC calibration, I2C TIMINGR, profiles."""
    return {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": "st", "family": "stm32g0", "device": "stm32g030f6",
            "core": {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
        },
        "provenance": {"primary": "stm32-overlay", "authored": "hand"},
        "memory": [],
        "clock": {
            "oscillators": {
                "hsi": {"freq": "16MHz", "kind": "rc-internal"},
                "hse": {"freq": "0Hz", "kind": "crystal-external", "optional": True},
            },
            "domains":  [{"id": "sysclk", "sources": ["hsi", "hse"]}],
            "profiles": [{"id": "post-reset", "kind": "post-reset",
                           "sysclk": "16MHz", "sysclk_source": "hsi"}],
        },
        "peripherals": [
            {
                "id": "adc1",
                "template": "adc",
                "calibration": {
                    "vrefint":    {"rom_addr": "0x1FFF75AA", "nominal_mv": 3000},
                    "ts_cal_low": {"rom_addr": "0x1FFF75A8", "temp_celsius": 30},
                },
            },
        ],
        "pinout": [],
    }


# ---------------------------------------------------------------------------
# Section-level merge
# ---------------------------------------------------------------------------


def test_pinout_replaced_by_open_pin_data_enrichment() -> None:
    primary = _svd_primary()
    open_pin = _open_pin_data_enrichment()
    result = merge_payloads(
        primary=primary, enrichments=(open_pin,), policy=STM32_MERGE_POLICY,
    )
    pinout = result.payload["pinout"]
    assert len(pinout) == 4
    assert any(p["signal"] == "VBAT" for p in pinout)
    # The placeholder RESET row from the primary is gone.
    assert all(p["signal"] != "RESET" for p in pinout)
    assert result.section_sources["pinout"] == "stm32-open-pin-data"


def test_memory_kept_from_primary_when_overlay_empty() -> None:
    primary = _svd_primary()
    overlay = _overlay_enrichment()
    overlay["memory"] = []   # explicit empty
    result = merge_payloads(
        primary=primary, enrichments=(overlay,), policy=STM32_MERGE_POLICY,
    )
    # Primary's flash + sram survive.
    ids = {m["id"] for m in result.payload["memory"]}
    assert {"flash", "sram"} <= ids


def test_clock_replaced_by_overlay_when_richer() -> None:
    primary = _svd_primary()
    overlay = _overlay_enrichment()
    result = merge_payloads(
        primary=primary, enrichments=(overlay,), policy=STM32_MERGE_POLICY,
    )
    clock = result.payload["clock"]
    assert "hsi" in clock["oscillators"]
    assert any(p["id"] == "post-reset" for p in clock.get("profiles", []))


# ---------------------------------------------------------------------------
# Per-peripheral enrichment
# ---------------------------------------------------------------------------


def test_pin_options_attached_to_correct_peripheral() -> None:
    primary = _svd_primary()
    open_pin = _open_pin_data_enrichment()
    result = merge_payloads(
        primary=primary, enrichments=(open_pin,), policy=STM32_MERGE_POLICY,
    )
    by_id = {p["id"]: p for p in result.payload["peripherals"]}
    assert "tx" in by_id["usart2"]["pin_options"]
    assert by_id["usart2"]["pin_options"]["tx"][0]["pin"] == "PA2"
    # adc1 isn't in the open-pin enrichment, so it stays unchanged.
    assert "pin_options" not in by_id["adc1"]


def test_calibration_attached_to_adc_only() -> None:
    primary = _svd_primary()
    overlay = _overlay_enrichment()
    result = merge_payloads(
        primary=primary, enrichments=(overlay,), policy=STM32_MERGE_POLICY,
    )
    by_id = {p["id"]: p for p in result.payload["peripherals"]}
    assert "calibration" in by_id["adc1"]
    assert by_id["adc1"]["calibration"]["vrefint"]["nominal_mv"] == 3000
    # USART2 has no calibration entry in any source.
    assert "calibration" not in by_id["usart2"]


def test_enrichment_does_not_introduce_new_peripherals() -> None:
    """Source-of-truth: the SVD declares which silicon has which
    peripherals.  An enrichment adding a phantom GPIOZ doesn't survive."""
    primary = _svd_primary()
    phantom = {
        "schema":     "alloy.device.v2.1",
        "identity":   primary["identity"],
        "provenance": {"primary": "stm32-cubemx", "authored": "auto"},
        "memory":     [],
        "clock":      primary["clock"],
        "peripherals":[{"id": "gpioz", "template": "gpio"}],
        "pinout":     [],
    }
    result = merge_payloads(
        primary=primary, enrichments=(phantom,), policy=STM32_MERGE_POLICY,
    )
    ids = {p["id"] for p in result.payload["peripherals"]}
    assert "gpioz" not in ids
    assert ids == {"adc1", "usart2"}


# ---------------------------------------------------------------------------
# Top-level provenance composition
# ---------------------------------------------------------------------------


def test_provenance_records_every_contributing_source() -> None:
    primary = _svd_primary()
    open_pin = _open_pin_data_enrichment()
    overlay = _overlay_enrichment()
    result = merge_payloads(
        primary=primary, enrichments=(open_pin, overlay), policy=STM32_MERGE_POLICY,
    )
    prov = result.payload["provenance"]
    assert prov["primary"] == "cmsis-svd:STM32G030.svd"
    assert "stm32-open-pin-data" in prov["secondary"]
    assert "stm32-overlay" in prov["secondary"]


def test_schema_lock_string_always_v2_1() -> None:
    primary = _svd_primary()
    result = merge_payloads(
        primary=primary, enrichments=(), policy=STM32_MERGE_POLICY,
    )
    assert result.payload["schema"] == "alloy.device.v2.1"


# ---------------------------------------------------------------------------
# Determinism + idempotence
# ---------------------------------------------------------------------------


def test_merge_is_deterministic() -> None:
    """Same inputs, two runs → equal output."""
    primary = _svd_primary()
    open_pin = _open_pin_data_enrichment()
    overlay = _overlay_enrichment()
    a = merge_payloads(primary=primary, enrichments=(open_pin, overlay), policy=STM32_MERGE_POLICY)
    b = merge_payloads(primary=primary, enrichments=(open_pin, overlay), policy=STM32_MERGE_POLICY)
    assert a.payload == b.payload
    assert a.section_sources == b.section_sources


# ---------------------------------------------------------------------------
# v2.1 schema validation of the merged output
# ---------------------------------------------------------------------------


def test_merged_payload_validates_via_v2_1_reader() -> None:
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    primary = _svd_primary()
    open_pin = _open_pin_data_enrichment()
    overlay = _overlay_enrichment()
    result = merge_payloads(
        primary=primary, enrichments=(open_pin, overlay), policy=STM32_MERGE_POLICY,
    )
    device = parse_device_payload(result.payload)
    assert device.schema == "alloy.device.v2.1"
    assert any(p.id == "adc1" and p.calibration is not None
               for p in device.peripherals)
    assert any(p.id == "usart2" and "tx" in p.pin_options
               for p in device.peripherals)


# ---------------------------------------------------------------------------
# Custom policy
# ---------------------------------------------------------------------------


def test_custom_policy_per_section() -> None:
    """A policy that swaps source priority surfaces a different winner."""
    primary = _svd_primary()
    enrichment = {
        "schema":     "alloy.device.v2.1",
        "identity":   primary["identity"],
        "provenance": {"primary": "alt-source", "authored": "auto"},
        "memory":     [{"id": "ccmram", "base": "0x10000000",
                         "size": "8KB", "access": "rw"}],
        "clock":      primary["clock"],
        "peripherals":primary["peripherals"],
        "pinout":     [],
    }
    custom = MergePolicy(
        name="alt", primary_source="cmsis-svd",
        section_priorities={"memory": ("alt-source", "cmsis-svd")},
    )
    result = merge_payloads(
        primary=primary, enrichments=(enrichment,), policy=custom,
    )
    assert result.payload["memory"][0]["id"] == "ccmram"
