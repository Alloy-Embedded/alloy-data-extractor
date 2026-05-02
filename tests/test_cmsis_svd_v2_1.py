"""Tests for the CMSIS-SVD → v2.1 primary extractor."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.extractors.cmsis_svd_v2_1 import (  # noqa: E402
    _normalise_access,
    _normalise_core,
    _parse_field_enum,
    _parse_field_position,
    _parse_int,
    extract_device,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", 0), ("0x10", 0x10), ("0X100", 0x100), ("#1010", 10),
        ("42", 42), ("", None), (None, None), ("not-a-number", None),
    ],
)
def test_parse_int(raw: str | None, expected: int | None) -> None:
    assert _parse_int(raw) == expected


@pytest.mark.parametrize(
    "svd,expected",
    [("read-only", "ro"), ("read-write", "rw"),
     ("write-only", "wo"), ("writeOnce", "wo"),
     ("read-writeOnce", "rw"), ("", None), (None, None)],
)
def test_normalise_access(svd: str | None, expected: str | None) -> None:
    assert _normalise_access(svd) == expected


@pytest.mark.parametrize(
    "svd_name,expected_isa,expected_bits,expected_fpu",
    [("CM3", "armv7-m", 32, False),
     ("CM4F", "armv7e-m", 32, True),
     ("CM7", "armv7e-m", 32, False),
     ("CM0plus", "armv6-m", 32, False),
     ("CM33", "armv8-m.main", 32, False),
     ("unknown-name", "unknown", 32, False)],
)
def test_normalise_core(svd_name: str, expected_isa: str,
                        expected_bits: int, expected_fpu: bool) -> None:
    isa, _, bits, fpu = _normalise_core(svd_name)
    assert isa == expected_isa
    assert bits == expected_bits
    assert fpu == expected_fpu


# ---------------------------------------------------------------------------
# Field-position parser — three SVD spellings
# ---------------------------------------------------------------------------


def _field_xml(body: str) -> ET.Element:
    return ET.fromstring(f"<field>{body}</field>")


def test_parse_field_position_bit_offset_and_width() -> None:
    el = _field_xml("<bitOffset>4</bitOffset><bitWidth>3</bitWidth>")
    assert _parse_field_position(el) == (4, 3)


def test_parse_field_position_lsb_msb() -> None:
    el = _field_xml("<lsb>4</lsb><msb>6</msb>")
    assert _parse_field_position(el) == (4, 3)


def test_parse_field_position_bit_range() -> None:
    el = _field_xml("<bitRange>[6:4]</bitRange>")
    assert _parse_field_position(el) == (4, 3)


def test_parse_field_enum_collects_named_values() -> None:
    el = _field_xml(
        "<enumeratedValues>"
        "<enumeratedValue><name>div_2</name><value>0x0</value></enumeratedValue>"
        "<enumeratedValue><name>div_4</name><value>0x1</value></enumeratedValue>"
        "<enumeratedValue><name>div_8</name><value>#10</value></enumeratedValue>"
        "</enumeratedValues>"
    )
    assert _parse_field_enum(el) == {"div_2": 0, "div_4": 1, "div_8": 2}


# ---------------------------------------------------------------------------
# Real-SVD round-trip — uses the cmsis-svd-data clone if present
# ---------------------------------------------------------------------------


_SVD_DIR = (
    ROOT.parent
    / "alloy-codegen"
    / ".cache"
    / "sources"
    / "cmsis-svd-data"
    / "data"
    / "STMicro"
)


def _have_svd(name: str) -> Path:
    path = _SVD_DIR / name
    if not path.is_file():
        pytest.skip(f"{name} not present (cmsis-svd-data not checked out)")
    return path


def test_extract_device_validates_via_v2_1_reader() -> None:
    """Output of the extractor must satisfy the v2.1 schema + IR."""
    sys.path.insert(0, str(ROOT.parent / "alloy-codegen" / "src"))
    from alloy_codegen.canonical_device_v2_1 import parse_device_payload  # noqa: E402

    svd = _have_svd("STM32G0B1.svd")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g0b1re", svd_path=svd,
    )
    device = parse_device_payload(payload)   # raises on schema violation
    assert device.schema == "alloy.device.v2.1"
    assert device.identity.vendor == "st"
    assert len(device.peripherals) >= 30
    assert len(device.templates)   >= 10


def test_extract_device_emits_irq_per_peripheral() -> None:
    svd = _have_svd("STM32G0B1.svd")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g0b1re", svd_path=svd,
    )
    # USART1 has IRQ 27 in STM32G0B1 SVDs.
    by_id = {p["id"]: p for p in payload["peripherals"]}
    assert "usart1" in by_id
    irq = by_id["usart1"].get("irq")
    assert irq is not None


def test_extract_device_clusters_templates_by_ip_class() -> None:
    """USART1 + USART2 + USART3 + USART4 share one ``usart`` template."""
    svd = _have_svd("STM32G0B1.svd")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g0b1re", svd_path=svd,
    )
    usart_instances = [p for p in payload["peripherals"]
                       if p["template"] == "usart"]
    # G0B1 ships USART1/2/3/4 + LPUART1/2 — at least the four USARTs share
    # a single template entry.
    assert len(usart_instances) >= 3
    assert "usart" in payload["templates"]


def test_extract_device_carries_field_enums_from_svd() -> None:
    """SVD's ``<enumeratedValues>`` survive into ``templates.<ip>.fields[<name>].enum``."""
    svd = _have_svd("STM32G0B1.svd")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g0b1re", svd_path=svd,
    )
    # At least one template field carries an enum block.
    found_enum = False
    for ip, t in payload["templates"].items():
        for fn, f in t.get("fields", {}).items():
            if "enum" in f and f["enum"]:
                found_enum = True
                break
        if found_enum:
            break
    assert found_enum


def test_extract_device_drops_per_row_provenance() -> None:
    svd = _have_svd("STM32G0B1.svd")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g0b1re", svd_path=svd,
    )
    # Per-row provenance is forbidden in v2.1 — every row must omit it.
    for per in payload["peripherals"]:
        assert "provenance" not in per
    for ip, t in payload["templates"].items():
        for f in t.get("fields", {}).values():
            assert "provenance" not in f


def test_extract_device_top_level_provenance_only() -> None:
    svd = _have_svd("STM32G0B1.svd")
    payload = extract_device(
        vendor="st", family="stm32g0", device="stm32g0b1re", svd_path=svd,
    )
    assert payload["provenance"]["primary"].startswith("cmsis-svd:")
    assert payload["provenance"]["authored"] == "auto"
