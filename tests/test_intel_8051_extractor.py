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


# ---------------------------------------------------------------------------
# Phase 2.1 — SFR bank / page tracking
# ---------------------------------------------------------------------------


_HEADER_WITH_PAGE_COMMENTS = textwrap.dedent("""\
    // SFR Page 0
    __sfr __at (0x80) P0;
    __sfr __at (0x88) TCON;

    // SFR Page 1
    __sfr __at (0xC1) PCON1;
    __sfr __at (0xC2) PWMCON1;

    /* Page 2 */
    __sfr __at (0xC1) AUXR2;
""")


_HEADER_WITH_PRAGMA = textwrap.dedent("""\
    __sfr __at (0x80) P0;
    #pragma sfr_bank 1
    __sfr __at (0xC1) PCON1;
    __sfr __at (0xC2) PWMCON1;
    #pragma sfr_page 0
    __sfr __at (0x90) P1;
""")


def test_page_comment_assigns_bank_to_subsequent_sfrs() -> None:
    sfrs = parse_sfr_header(_HEADER_WITH_PAGE_COMMENTS)
    by_key = {(s.name, s.bank): s for s in sfrs}
    # Page-0 SFRs.
    assert by_key[("P0", 0)].address == 0x80
    assert by_key[("TCON", 0)].address == 0x88
    # Page-1 SFRs.
    assert by_key[("PCON1", 1)].address == 0xC1
    assert by_key[("PWMCON1", 1)].address == 0xC2
    # Page-2 SFR shares an address with PCON1 but lives in a different bank.
    assert by_key[("AUXR2", 2)].address == 0xC1


def test_pragma_sfr_bank_directive_is_honored() -> None:
    sfrs = parse_sfr_header(_HEADER_WITH_PRAGMA)
    by_name = {s.name: s for s in sfrs}
    assert by_name["P0"].bank == 0
    assert by_name["PCON1"].bank == 1
    assert by_name["PWMCON1"].bank == 1
    # `#pragma sfr_page 0` resets the active bank.
    assert by_name["P1"].bank == 0


def test_same_address_different_banks_kept_distinct() -> None:
    """A modern N76/EFM8-style header reuses 0xC1 across pages —
    the parser must not dedup across banks."""
    sfrs = parse_sfr_header(_HEADER_WITH_PAGE_COMMENTS)
    pcon1 = next(s for s in sfrs if s.name == "PCON1")
    auxr2 = next(s for s in sfrs if s.name == "AUXR2")
    assert pcon1.address == auxr2.address == 0xC1
    assert pcon1.bank != auxr2.bank


def test_payload_peripherals_carry_bank_for_non_zero_page(tmp_path: Path) -> None:
    header_path = tmp_path / "n76e003.h"
    header_path.write_text(_HEADER_WITH_PAGE_COMMENTS, encoding="utf-8")
    ext = resolve_extractor("nuvoton", "n76")
    request = ExtractionRequest(
        vendor="nuvoton",
        family="n76",
        device="n76e003at20",
        source_paths={"intel-8051": header_path},
        revision="header-test",
    )
    payload = ext.extract(request).payload
    by_name = {(p["name"], p.get("bank", 0)): p for p in payload["peripherals"]}
    # Page-0 entries don't carry a bank field.
    assert "bank" not in by_name[("P0", 0)]
    # Page-1+ entries do carry it.
    assert by_name[("PCON1", 1)]["bank"] == 1
    assert by_name[("AUXR2", 2)]["bank"] == 2


# ---------------------------------------------------------------------------
# Phase 2.2 — Indirect-addressing decoration
# ---------------------------------------------------------------------------


_HEADER_WITH_ADDR_MODES = textwrap.dedent("""\
    __idata __sfr __at (0xE0) ACC;
    __xdata __sfr __at (0xE1) AUXR;
    __pdata __sfr __at (0xE2) PFLAG;
    __bdata __sfr __at (0xE3) FLAGS;
    __sfr __at (0xE4) PSW;
    __idata __sbit __at (0xE0) ACC_0;
""")


def test_idata_keyword_marks_register_indirect() -> None:
    sfrs = parse_sfr_header(_HEADER_WITH_ADDR_MODES)
    by_name = {s.name: s for s in sfrs}
    assert by_name["ACC"].addressing_mode == "indirect"
    assert by_name["AUXR"].addressing_mode == "external"
    assert by_name["PFLAG"].addressing_mode == "paged"
    assert by_name["FLAGS"].addressing_mode == "bit-addressable"
    # Bare declaration falls back to direct.
    assert by_name["PSW"].addressing_mode == "direct"


def test_sbit_with_idata_keyword_overrides_default_bit_mode() -> None:
    sfrs = parse_sfr_header(_HEADER_WITH_ADDR_MODES)
    by_name = {s.name: s for s in sfrs}
    assert by_name["ACC_0"].is_bit
    assert by_name["ACC_0"].addressing_mode == "indirect"


def test_payload_registers_carry_bank_and_addressing_mode(tmp_path: Path) -> None:
    header_path = tmp_path / "synth.h"
    header_path.write_text(
        _HEADER_WITH_PAGE_COMMENTS + _HEADER_WITH_ADDR_MODES, encoding="utf-8"
    )
    ext = resolve_extractor("silabs", "efm8")
    request = ExtractionRequest(
        vendor="silabs",
        family="efm8",
        device="efm8bb1",
        source_paths={"intel-8051": header_path},
        revision="r",
    )
    payload = ext.extract(request).payload
    by_name = {(r["name"], r["bank"]): r for r in payload["registers"]}
    assert by_name[("ACC", 2)]["addressing_mode"] == "indirect"
    assert by_name[("PSW", 2)]["addressing_mode"] == "direct"
    assert by_name[("P0", 0)]["addressing_mode"] == "direct"
