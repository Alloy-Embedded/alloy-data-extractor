"""Tests for the TI MSP430 extractor (Phase 3.3)."""

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
from alloy_data_extractor.extractors.msp430 import (  # noqa: E402
    Msp430PinPort,
    Msp430Register,
    _discover_pin_ports,
    parse_msp430_header,
)

# Synthetic MSP430G2553-flavour header excerpt — only the
# directives the parser cares about, no real CCS bloat.
_SYNTH_HEADER = textwrap.dedent("""\
    /* MSP430G2553 synthetic header */
    #define DCOCTL_              0x0056    /* DCO Frequency Control */
    #define BCSCTL1_             0x0057    /* Basic Clock System Control 1 */
    #define BCSCTL2_             0x0058
    #define P1IN_                0x0020
    #define P1OUT_               0x0021
    #define P1DIR_               0x0022
    #define P1IE_                0x0025
    #define P1SEL_               0x0026
    #define P1SEL2_              0x0041
    #define P2IN_                0x0028
    #define P2OUT_               0x0029
    #define P2SEL_               0x002E
    #define UCA0CTL0_            0x0060
    #define UCA0CTL1_            0x0061
    #define UCA0BR0_             0x0062
    #define UCA0BR1_             0x0063
    #define WDTCTL_              0x0120
    #define TAR_                 0x0170
    #define TACCR0_              0x0172
    #define TACTL_               0x0160
    /* width-declaring forms */
    sfrb(P1IN,    P1IN_);
    sfrw(WDTCTL,  WDTCTL_);
    sfrw(TAR,     TAR_);
    sfrw(TACCR0,  TACCR0_);
    sfrw(TACTL,   TACTL_);
    /* These two should be skipped by the parser because they
       lack the trailing underscore (they are macro
       dereferences, not address constants). */
    #define DCOCTL              (HWREG8(DCOCTL_))
    #define P1IN                (HWREG8(P1IN_))
""")


def test_parse_extracts_address_constants() -> None:
    registers = parse_msp430_header(_SYNTH_HEADER)
    by_name = {r.name: r for r in registers}
    assert by_name["DCOCTL"].address == 0x56
    assert by_name["P1IN"].address == 0x20
    assert by_name["UCA0BR1"].address == 0x63


def test_parse_skips_macro_dereferences() -> None:
    """The `#define DCOCTL (HWREG8(DCOCTL_))` form must NOT
    appear as a register — only the `_`-suffixed address
    constants do."""
    registers = parse_msp430_header(_SYNTH_HEADER)
    names = {r.name for r in registers}
    # 'DCOCTL' is the address constant (no trailing _) — it's
    # the same as the parsed name (the trailing _ is stripped).
    # The macro form `(HWREG8(...))` simply doesn't match the
    # regex so isn't a duplicate.
    assert len(names) == len(list(registers))


def test_parse_dedups_repeated_definitions() -> None:
    text = "#define X_ 0x10\n#define X_ 0x10\n"
    registers = parse_msp430_header(text)
    assert len([r for r in registers if r.name == "X"]) == 1


def test_parse_returns_empty_for_irrelevant_text() -> None:
    assert parse_msp430_header("/* prose only */") == ()


def test_extractor_resolves_for_ti_msp430_family() -> None:
    ext = resolve_extractor("ti", "msp430")
    assert ext.extractor_id == "msp430"


def test_extractor_payload_shape(tmp_path: Path) -> None:
    header_path = tmp_path / "msp430g2553.h"
    header_path.write_text(_SYNTH_HEADER, encoding="utf-8")

    ext = resolve_extractor("ti", "msp430")
    request = ExtractionRequest(
        vendor="ti",
        family="msp430",
        device="msp430g2553",
        source_paths={"msp430": header_path},
        revision="hdr-test",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["core"] == "msp430"
    assert result.payload["provenance"]["source_id"] == "msp430"

    register_names = {r["name"] for r in result.payload["registers"]}
    assert {"DCOCTL", "BCSCTL1", "P1IN", "UCA0CTL0"}.issubset(register_names)

    peripheral_names = {p["name"] for p in result.payload["peripherals"]}
    # Port grouping: P1IN/P1OUT/P1DIR/P1IE → P1.
    assert "P1" in peripheral_names
    assert "P2" in peripheral_names
    # USCI grouping: UCA0CTL0/UCA0CTL1/UCA0BR0/UCA0BR1 → UCA0.
    assert "UCA0" in peripheral_names


def test_p1in_grouped_under_p1_peripheral() -> None:
    registers = parse_msp430_header(_SYNTH_HEADER)
    p1_addrs = sorted(r.address for r in registers if r.name.startswith("P1"))
    # P1IN at 0x20 should be the lowest of the P1 group.
    assert p1_addrs[0] == 0x20


def test_extractor_raises_value_error_when_header_missing() -> None:
    ext = resolve_extractor("ti", "msp430")
    request = ExtractionRequest(
        vendor="ti",
        family="msp430",
        device="x",
        source_paths={},
        revision="r",
    )
    with pytest.raises(ValueError, match="msp430"):
        ext.extract(request)


def test_register_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    reg = Msp430Register(name="P0", address=0x80)
    with pytest.raises(FrozenInstanceError):
        reg.address = 0x90  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 2.1 — 16-bit register width inference
# ---------------------------------------------------------------------------


def test_sfrw_declaration_marks_register_as_16bit() -> None:
    registers = parse_msp430_header(_SYNTH_HEADER)
    by_name = {r.name: r for r in registers}
    assert by_name["WDTCTL"].width_bits == 16
    assert by_name["TAR"].width_bits == 16
    assert by_name["TACCR0"].width_bits == 16


def test_sfrb_declaration_keeps_register_8bit() -> None:
    registers = parse_msp430_header(_SYNTH_HEADER)
    by_name = {r.name: r for r in registers}
    assert by_name["P1IN"].width_bits == 8


def test_name_pattern_fallback_marks_known_16bit_when_undeclared() -> None:
    """No `sfrw`/`sfrb` declarations — the parser falls back to
    the conservative name pattern for known 16-bit families."""
    text = textwrap.dedent("""\
        #define WDTCTL_  0x0120
        #define TAR_     0x0170
        #define TACCR1_  0x0174
        #define TACTL_   0x0160
        #define ADC10CTL0_ 0x01B0
        #define UCA0BRW_   0x05CE
        #define MPY32H_  0x014E
        #define DCOCTL_  0x0056
    """)
    by_name = {r.name: r.width_bits for r in parse_msp430_header(text)}
    assert by_name["WDTCTL"] == 16
    assert by_name["TAR"] == 16
    assert by_name["TACCR1"] == 16
    assert by_name["TACTL"] == 16
    assert by_name["ADC10CTL0"] == 16
    assert by_name["UCA0BRW"] == 16
    assert by_name["MPY32H"] == 16
    # DCOCTL is not in the 16-bit pattern set → stays 8-bit.
    assert by_name["DCOCTL"] == 8


def test_sfrw_with_underscore_form_recognised() -> None:
    """The `sfrw_(NAME, addr)` form (used by some legacy headers)
    must also lift the width to 16."""
    text = textwrap.dedent("""\
        #define FOO_ 0x0200
        sfrw_(FOO, 0x0200);
    """)
    registers = parse_msp430_header(text)
    assert registers[0].width_bits == 16


# ---------------------------------------------------------------------------
# Phase 2.2 — Pin discovery from PxIN / PxSEL
# ---------------------------------------------------------------------------


def test_discover_pin_ports_classifies_two_bit_mux() -> None:
    """P1 has both SEL and SEL2 → 2-bit mux (4 AFs/pin); P2 has
    only SEL → 1-bit mux."""
    registers = parse_msp430_header(_SYNTH_HEADER)
    ports = {p.name: p for p in _discover_pin_ports(registers)}
    assert ports["P1"].mux_select_bits == 2
    assert ports["P2"].mux_select_bits == 1


def test_discover_pin_ports_handles_sel0_sel1_pair() -> None:
    """MSP430FR-flavour parts use PxSEL0 + PxSEL1 — the classifier
    must recognise that as a 2-bit mux too."""
    text = textwrap.dedent("""\
        #define P3IN_   0x0220
        #define P3OUT_  0x0222
        #define P3DIR_  0x0224
        #define P3SEL0_ 0x0226
        #define P3SEL1_ 0x0228
    """)
    ports = _discover_pin_ports(parse_msp430_header(text))
    assert len(ports) == 1
    assert ports[0].name == "P3"
    assert ports[0].mux_select_bits == 2


def test_discover_pin_ports_zero_bits_when_no_sel_register() -> None:
    text = textwrap.dedent("""\
        #define P5IN_  0x0240
        #define P5OUT_ 0x0241
        #define P5DIR_ 0x0242
    """)
    ports = _discover_pin_ports(parse_msp430_header(text))
    assert len(ports) == 1
    assert ports[0].mux_select_bits == 0


def test_discover_pin_ports_skips_orphan_sel_registers() -> None:
    """A bare PxSEL with no matching PxIN must not become a port —
    we rely on the IN register as the port-existence signal."""
    text = "#define P9SEL_ 0x0230\n"
    ports = _discover_pin_ports(parse_msp430_header(text))
    assert ports == ()


def test_extractor_payload_carries_pin_entries(tmp_path: Path) -> None:
    header_path = tmp_path / "msp430g2553.h"
    header_path.write_text(_SYNTH_HEADER, encoding="utf-8")

    ext = resolve_extractor("ti", "msp430")
    request = ExtractionRequest(
        vendor="ti",
        family="msp430",
        device="msp430g2553",
        source_paths={"msp430": header_path},
        revision="hdr-test",
    )
    payload = ext.extract(request).payload

    pins = payload["pins"]
    by_name = {p["name"]: p for p in pins}
    # 8 pins per port × 2 ports → 16 pins.
    assert len(pins) == 16
    assert by_name["P1.0"]["bit"] == 0
    assert by_name["P1.0"]["mux_select_bits"] == 2
    assert by_name["P2.7"]["mux_select_bits"] == 1
    # AFs intentionally empty — datasheet-only.
    assert all(p["alternate_functions"] == [] for p in pins)


def test_pin_port_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    port = Msp430PinPort(name="P1", in_address=0x20, pin_count=8, mux_select_bits=2)
    with pytest.raises(FrozenInstanceError):
        port.pin_count = 4  # type: ignore[misc]
