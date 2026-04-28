"""Tests for the 8051-derivative extractor (Phase 4.2)."""

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
    resolve_extractor,
)
from alloy_data_extractor.extractors.intel_8051 import (  # noqa: E402
    Sfr,
    parse_sfr_header,
)

_HEADER_NUVOTON_LIKE = textwrap.dedent("""\
    // Nuvoton-style 8051 SFR header
    __sfr __at (0x80) P0;
    __sfr __at (0x90) P1;
    __sfr __at (0xA0) P2;
    __sbit __at (0x80) P0_0;
    __sbit __at (0x81) P0_1;
    sfr __at (0x88) TCON;
    sfr __at (0x89) TMOD;
    sfr16 __at (0x82) DPTR;
""")


_HEADER_SDCC_FORM = textwrap.dedent("""\
    sfr at 0x80 P0;
    sfr at 0x88 TCON;
    sfr at 0x89 TMOD;
""")


def test_parse_finds_basic_sfrs() -> None:
    sfrs = parse_sfr_header(_HEADER_NUVOTON_LIKE)
    by_name = {s.name: s for s in sfrs}
    assert by_name["P0"].address == 0x80
    assert by_name["P1"].address == 0x90
    assert by_name["TCON"].address == 0x88
    assert by_name["DPTR"].width_bits == 16


def test_parse_handles_sbit_declarations() -> None:
    sfrs = parse_sfr_header(_HEADER_NUVOTON_LIKE)
    by_name = {s.name: s for s in sfrs}
    assert by_name["P0_0"].is_bit is True
    assert by_name["P0_0"].width_bits == 1


def test_parse_handles_sdcc_form_without_underscores() -> None:
    sfrs = parse_sfr_header(_HEADER_SDCC_FORM)
    addrs = {s.name: s.address for s in sfrs}
    assert addrs == {"P0": 0x80, "TCON": 0x88, "TMOD": 0x89}


def test_parse_dedups_repeated_declarations() -> None:
    text = "__sfr __at (0x80) P0;\n__sfr __at (0x80) P0;\n"
    sfrs = parse_sfr_header(text)
    assert len([s for s in sfrs if s.name == "P0"]) == 1


def test_parse_returns_empty_for_no_sfrs() -> None:
    assert parse_sfr_header("// just a comment\nint main(void) { return 0; }") == ()


def test_extractor_resolves_for_each_admitted_8051_family() -> None:
    pairs = [
        ("nuvoton", "n76"),
        ("nuvoton", "n79"),
        ("silabs", "efm8"),
        ("stc", "stc15w"),
    ]
    for vendor, family in pairs:
        ext = resolve_extractor(vendor, family)
        assert ext.extractor_id == "intel-8051"


def test_extractor_payload_contains_peripherals_and_registers(tmp_path: Path) -> None:
    header_path = tmp_path / "synth.h"
    header_path.write_text(_HEADER_NUVOTON_LIKE, encoding="utf-8")

    ext = resolve_extractor("nuvoton", "n76")
    request = ExtractionRequest(
        vendor="nuvoton",
        family="n76",
        device="n76e003at20",
        source_paths={"intel-8051": header_path},
        revision="header-test",
    )
    result = ext.extract(request)

    assert result.payload["identity"]["core"] == "i8051"
    assert result.payload["provenance"]["source_id"] == "intel-8051"
    register_names = {r["name"] for r in result.payload["registers"]}
    assert {"P0", "P1", "P2", "TCON", "TMOD", "DPTR"}.issubset(register_names)
    peripheral_names = {p["name"] for p in result.payload["peripherals"]}
    # P0/P1/P2 group as separate "peripherals" because each gets a
    # distinct numeric suffix.
    assert "P0" in peripheral_names
    assert "P1" in peripheral_names


def test_extractor_raises_value_error_when_header_missing() -> None:
    ext = resolve_extractor("nuvoton", "n76")
    request = ExtractionRequest(
        vendor="nuvoton",
        family="n76",
        device="x",
        source_paths={},
        revision="r",
    )
    with pytest.raises(ValueError, match="intel-8051"):
        ext.extract(request)


def test_sfr_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    sfr = Sfr(name="P0", address=0x80)
    with pytest.raises(FrozenInstanceError):
        sfr.address = 0x90  # type: ignore[misc]
