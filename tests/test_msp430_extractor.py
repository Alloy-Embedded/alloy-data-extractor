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
    Msp430Register,
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
    #define P2IN_                0x0028
    #define P2OUT_               0x0029
    #define UCA0CTL0_            0x0060
    #define UCA0CTL1_            0x0061
    #define UCA0BR0_             0x0062
    #define UCA0BR1_             0x0063
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
