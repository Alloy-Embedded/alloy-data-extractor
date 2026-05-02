"""Tests for the v1 → v2.1 converter (Phase 7 prep)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from convert_v1_to_v2_1 import (  # noqa: E402
    _bytes_with_unit,
    _hz_with_unit,
    _normalise_access,
    convert_payload,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (1024, "1KB"),
        (32 * 1024, "32KB"),
        (2 * 1024 * 1024, "2MB"),
        (1, "1B"),
        (None, None),
    ],
)
def test_bytes_with_unit(raw: int | None, expected: str | None) -> None:
    assert _bytes_with_unit(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (8_000_000, "8MHz"),
        (32_768, "32768Hz"),    # not a multiple of 1000 → falls through
        (16_000_000, "16MHz"),
        (1_000, "1kHz"),
        (None, None),
    ],
)
def test_hz_with_unit(raw: int | None, expected: str | None) -> None:
    assert _hz_with_unit(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("read-write", "rw"),
        ("read-only", "ro"),
        ("readonly", "ro"),
        ("rw", "rw"),
        ("x", "rx"),
        ("rwx", "rwx"),
        (None, "rwx"),       # default
    ],
)
def test_normalise_access(raw: str | None, expected: str) -> None:
    assert _normalise_access(raw) == expected


# ---------------------------------------------------------------------------
# Top-level convert_payload — minimum viable v1 input
# ---------------------------------------------------------------------------


_MINIMAL_V1 = {
    "schema_version": "1.2.0",
    "identity": {
        "vendor": "st",
        "family": "stm32g0",
        "device": "stm32g030f6",
        "core": "cortex-m0plus",
    },
    "provenance": {
        "source_id": "cmsis-svd",
        "source_path": "STM32G030.svd",
        "patch_ids": [],
    },
    "memories": [
        {"name": "flash", "base_address": 0x08000000, "size_bytes": 32768, "access": "rx"},
        {"name": "sram",  "base_address": 0x20000000, "size_bytes":  8192, "access": "rw"},
    ],
    "peripherals": [
        {"name": "GPIOA", "ip_name": "gpio", "ip_version": "g0_v1",
         "base_address": 0x50000000,
         "rcc_enable_signal": "RCC_IOPENR.IOPAEN"},
        {"name": "USART2", "ip_name": "usart", "ip_version": "g0_v1",
         "base_address": 0x40004400,
         "rcc_enable_signal": "RCC_APBENR1.USART2EN"},
    ],
    "interrupts": [
        {"name": "USART2_IRQHandler", "line": 28, "peripheral": "USART2"},
    ],
    "registers": [
        {"register_id": "register:gpioa:moder", "peripheral": "GPIOA",
         "name": "MODER", "offset_bytes": 0x00},
        {"register_id": "register:usart2:cr1",  "peripheral": "USART2",
         "name": "CR1",   "offset_bytes": 0x0C},
    ],
    "register_fields": [
        {"field_id": "field:gpioa:moder:mode2",
         "register_id": "register:gpioa:moder", "peripheral": "GPIOA",
         "register_name": "MODER", "name": "MODE2",
         "bit_offset": 4, "bit_width": 2},
        {"field_id": "field:usart2:cr1:ue",
         "register_id": "register:usart2:cr1", "peripheral": "USART2",
         "register_name": "CR1", "name": "UE",
         "bit_offset": 13, "bit_width": 1},
    ],
    "pins": [
        {"name": "PA0", "port": "A", "number": 0},
        {"name": "PA1", "port": "A", "number": 1},
    ],
    # alloy-codegen synthesised — must NOT survive into v2.1
    "route_operations": [{"operation_id": "operation:foo"}],
    "vector_slots":     [{"slot": 0, "kind": "reset"}],
}


def test_top_level_schema_const_set() -> None:
    out = convert_payload(_MINIMAL_V1)
    assert out["schema"] == "alloy.device.v2.1"


def test_synthesised_sections_are_dropped() -> None:
    out = convert_payload(_MINIMAL_V1)
    for forbidden in ("route_operations", "vector_slots", "interrupt_bindings",
                      "connection_candidates", "ip_blocks"):
        assert forbidden not in out, f"{forbidden} survived the conversion"


def test_identity_preserves_vendor_family_device() -> None:
    out = convert_payload(_MINIMAL_V1)
    assert out["identity"]["vendor"] == "st"
    assert out["identity"]["family"] == "stm32g0"
    assert out["identity"]["device"] == "stm32g030f6"
    assert out["identity"]["core"]["name"] == "cortex-m0plus"
    assert out["identity"]["core"]["isa"] == "armv6-m"
    assert out["identity"]["core"]["bits"] == 32


def test_memory_uses_unit_suffixes() -> None:
    out = convert_payload(_MINIMAL_V1)
    flash = next(m for m in out["memory"] if m["id"] == "flash")
    assert flash["size"] == "32KB"
    sram = next(m for m in out["memory"] if m["id"] == "sram")
    assert sram["size"] == "8KB"
    assert sram["access"] == "rw"


def test_templates_clustered_by_ip_name() -> None:
    out = convert_payload(_MINIMAL_V1)
    templates = out["templates"]
    # gpio template should carry MODER + the MODE2 field range
    assert "gpio" in templates
    assert "moder.mode2" in templates["gpio"]["fields"]
    assert templates["gpio"]["fields"]["moder.mode2"]["bits"] == [4, 5]
    # usart template should carry CR1 + the UE bit
    assert "usart" in templates
    assert "cr1.ue" in templates["usart"]["fields"]
    assert templates["usart"]["fields"]["cr1.ue"]["bit"] == 13


def test_peripherals_reference_template_by_ip_name() -> None:
    out = convert_payload(_MINIMAL_V1)
    by_id = {p["id"]: p for p in out["peripherals"]}
    assert by_id["gpioa"]["template"]   == "gpio"
    assert by_id["gpioa"]["ip_version"] == "g0_v1"
    assert by_id["usart2"]["template"]  == "usart"
    # rcc.en preserved
    assert by_id["gpioa"]["rcc"]["en"]  == "RCC_IOPENR.IOPAEN"
    # IRQ associated
    assert by_id["usart2"]["irq"]["num"] == 28


def test_provenance_carries_top_level_only() -> None:
    out = convert_payload(_MINIMAL_V1)
    assert out["provenance"]["primary"].startswith("cmsis-svd")
    assert out["provenance"]["authored"] == "auto+hand"
    # Per-row provenance never appears in the converted output.
    for per in out["peripherals"]:
        assert "provenance" not in per
    for mem in out["memory"]:
        assert "provenance" not in mem


def test_converted_payload_validates_via_v2_1_schema() -> None:
    """The whole point — emit a payload the new reader accepts."""
    sys.path.insert(
        0,
        str(ROOT.parent / "alloy-codegen" / "src"),
    )
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    out = convert_payload(_MINIMAL_V1)
    device = parse_device_payload(out)
    assert device.schema == "alloy.device.v2.1"
    assert device.identity.device == "stm32g030f6"
    assert len(device.memory) == 2
    assert len(device.peripherals) == 2
