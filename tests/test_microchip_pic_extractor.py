"""Tests for the Microchip PIC extractor (Phase 3.1).

Reuses the Phase 1.2 ATDF parser; the bulk of testing happens
in test_phase1_real_extractors_e2e.py.  Here we cover PIC-
specific concerns: per-family core mapping when ATDF is mute,
ATDF-path discovery via DFP cache layouts, family resolution.
"""

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

_ATDF_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0"?>
    <avr-tools-device-file>
      <devices>
        <device architecture="{arch}" family="PIC" name="{name}">
          <peripherals>
            <module name="UART">
              <instance name="UART0">
                <register-group name="UART0" address-space="base" offset="0xF80"/>
              </instance>
            </module>
          </peripherals>
          <interrupts>
            <interrupt index="5" name="UART0" module-instance="UART0"/>
          </interrupts>
        </device>
      </devices>
    </avr-tools-device-file>
""")


@pytest.mark.parametrize(
    ("vendor", "family"),
    [
        ("microchip", "pic12f"),
        ("microchip", "pic16f"),
        ("microchip", "pic18"),
        ("microchip", "pic24f"),
        ("microchip", "dspic33"),
        ("microchip", "pic32mx"),
        ("microchip", "pic32mz"),
        ("microchip", "pic32mk"),
    ],
)
def test_pic_extractor_resolves_for_admitted_pic_family(
    vendor: str, family: str
) -> None:
    ext = resolve_extractor(vendor, family)
    assert ext.extractor_id == "microchip-pic"


def test_pic_extractor_extracts_via_atdf(tmp_path: Path) -> None:
    atdf = tmp_path / "PIC18F47Q10.atdf"
    atdf.write_text(_ATDF_TEMPLATE.format(arch="PIC18", name="PIC18F47Q10"), encoding="utf-8")

    ext = resolve_extractor("microchip", "pic18")
    request = ExtractionRequest(
        vendor="microchip",
        family="pic18",
        device="pic18f47q10",
        source_paths={"atdf": atdf},
        revision="pic-test",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["core"] == "pic18"
    assert result.payload["provenance"]["source_id"] == "microchip-pic"
    assert any(p["name"] == "UART0" for p in result.payload["peripherals"])
    assert any(i["line"] == 5 for i in result.payload["interrupts"])


def test_pic_extractor_falls_back_to_family_core_when_atdf_silent(
    tmp_path: Path,
) -> None:
    """Older PIC ATDFs sometimes omit the architecture attribute;
    the extractor should fall back to the family-default core."""
    atdf = tmp_path / "PIC16F18877.atdf"
    atdf.write_text(_ATDF_TEMPLATE.format(arch="", name="PIC16F18877"), encoding="utf-8")

    ext = resolve_extractor("microchip", "pic16f")
    request = ExtractionRequest(
        vendor="microchip",
        family="pic16f",
        device="pic16f18877",
        source_paths={"atdf": atdf},
        revision="pic-test",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["core"] == "pic16f"


def test_pic_extractor_discovers_atdf_via_dfp_cache_root(tmp_path: Path) -> None:
    """When given a DFP-cache root, the extractor walks for the
    upper-cased device name."""
    dfp_root = tmp_path / "dfp"
    nested_dir = dfp_root / "pic-2024-01" / "pic18" / "atdf"
    nested_dir.mkdir(parents=True)
    atdf = nested_dir / "PIC18F47Q10.atdf"
    atdf.write_text(_ATDF_TEMPLATE.format(arch="PIC18", name="PIC18F47Q10"), encoding="utf-8")

    ext = resolve_extractor("microchip", "pic18")
    request = ExtractionRequest(
        vendor="microchip",
        family="pic18",
        device="pic18f47q10",
        source_paths={"microchip-pic": dfp_root},
        revision="pic-test",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["core"] == "pic18"


def test_pic_extractor_raises_value_error_when_atdf_missing(tmp_path: Path) -> None:
    ext = resolve_extractor("microchip", "pic18")
    request = ExtractionRequest(
        vendor="microchip",
        family="pic18",
        device="x",
        source_paths={},
        revision="r",
    )
    with pytest.raises(ValueError, match="microchip-pic"):
        ext.extract(request)


# ---------------------------------------------------------------------------
# Phase 2 — per-arch IR projection (banks / indirect / DSP / CP0)
# ---------------------------------------------------------------------------


_PIC18_BANKED_ATDF = textwrap.dedent("""\
    <?xml version="1.0"?>
    <avr-tools-device-file>
      <devices>
        <device architecture="PIC18" family="PIC" name="PIC18F47Q10">
          <address-spaces>
            <address-space name="data" id="data" size="0x1000">
              <memory-segment name="BANK0_GPR"  start="0x20"  size="0x60" type="ram" rw="RW"/>
              <memory-segment name="BANK1_GPR"  start="0xa0"  size="0x60" type="ram" rw="RW"/>
              <memory-segment name="BANK15_SFR" start="0xf80" size="0x80" type="io"  rw="RW"/>
              <memory-segment name="LINEAR"     start="0x2000" size="0x800" type="ram" rw="RW"/>
            </address-space>
            <address-space name="prog" id="prog" size="0x10000">
              <memory-segment name="PROGRAM_FLASH" start="0" size="0x10000" type="flash" rw="R"/>
            </address-space>
          </address-spaces>
          <peripherals>
            <module name="UART">
              <instance name="UART0">
                <register-group name="UART0" address-space="data" offset="0xF80"/>
              </instance>
            </module>
          </peripherals>
          <interrupts/>
        </device>
      </devices>
    </avr-tools-device-file>
""")


def test_pic18_projection_carries_memories_and_banked_extension(tmp_path: Path) -> None:
    atdf = tmp_path / "PIC18F47Q10.atdf"
    atdf.write_text(_PIC18_BANKED_ATDF, encoding="utf-8")
    ext = resolve_extractor("microchip", "pic18")
    payload = ext.extract(
        ExtractionRequest(
            vendor="microchip",
            family="pic18",
            device="pic18f47q10",
            source_paths={"atdf": atdf},
            revision="r",
        )
    ).payload

    # Memory regions surface for every address-space.
    memory_names = {m["name"] for m in payload["memories"]}
    assert memory_names == {"BANK0_GPR", "BANK1_GPR", "BANK15_SFR", "LINEAR", "PROGRAM_FLASH"}

    # PIC8 carve-out projects banks deterministically.
    banks = payload["arch_extensions"]["banked_memory"]
    by_index = {b["bank"]: b for b in banks}
    assert by_index[0]["kind"] == "GPR"
    assert by_index[0]["base_address"] == 0x20
    assert by_index[0]["size_bytes"] == 0x60
    assert by_index[1]["base_address"] == 0xA0
    assert by_index[15]["kind"] == "SFR"


_DSPIC33_ATDF = textwrap.dedent("""\
    <?xml version="1.0"?>
    <avr-tools-device-file>
      <devices>
        <device architecture="DSPIC33" family="DSPIC" name="DSPIC33EP512MU810">
          <peripherals>
            <module name="CPU">
              <instance name="W0">
                <register-group name="W0" address-space="data" offset="0x00"/>
              </instance>
              <instance name="W1">
                <register-group name="W1" address-space="data" offset="0x02"/>
              </instance>
              <instance name="W15">
                <register-group name="W15" address-space="data" offset="0x1E"/>
              </instance>
              <instance name="TBLPAG">
                <register-group name="TBLPAG" address-space="data" offset="0x32"/>
              </instance>
              <instance name="DSRPAG">
                <register-group name="DSRPAG" address-space="data" offset="0x34"/>
              </instance>
              <instance name="CORCON">
                <register-group name="CORCON" address-space="data" offset="0x44"/>
              </instance>
              <instance name="ACCAL">
                <register-group name="ACCAL" address-space="data" offset="0x22"/>
              </instance>
              <instance name="MODCON">
                <register-group name="MODCON" address-space="data" offset="0x46"/>
              </instance>
            </module>
            <module name="UART">
              <instance name="UART1">
                <register-group name="UART1" address-space="data" offset="0x220"/>
              </instance>
            </module>
          </peripherals>
          <interrupts/>
        </device>
      </devices>
    </avr-tools-device-file>
""")


def test_dspic33_projection_separates_indirect_and_dsp_carves(tmp_path: Path) -> None:
    atdf = tmp_path / "DSPIC33EP512MU810.atdf"
    atdf.write_text(_DSPIC33_ATDF, encoding="utf-8")
    ext = resolve_extractor("microchip", "dspic33")
    payload = ext.extract(
        ExtractionRequest(
            vendor="microchip",
            family="dspic33",
            device="dspic33ep512mu810",
            source_paths={"atdf": atdf},
            revision="r",
        )
    ).payload

    extensions = payload["arch_extensions"]

    # W register file + TBLPAG/DSRPAG flow into the indirect carve-out.
    indirect_names = {r["name"] for r in extensions["indirect_pointer_registers"]}
    assert {"W0", "W1", "W15", "TBLPAG", "DSRPAG"}.issubset(indirect_names)
    assert "UART1" not in indirect_names

    # DSP SFRs carve into a separate list — and don't overlap the
    # indirect-pointer carve-out.
    dsp_names = {r["name"] for r in extensions["dsp_sfrs"]}
    assert dsp_names == {"CORCON", "ACCAL", "MODCON"}
    assert dsp_names.isdisjoint(indirect_names)

    # `peripherals` keeps its full inventory (carve-outs are
    # views, not removals).
    peripheral_names = {p["name"] for p in payload["peripherals"]}
    assert {"W0", "TBLPAG", "CORCON", "UART1"}.issubset(peripheral_names)


def test_pic24_projection_emits_indirect_pointers_only(tmp_path: Path) -> None:
    atdf = tmp_path / "PIC24FJ128GA010.atdf"
    atdf.write_text(_DSPIC33_ATDF, encoding="utf-8")  # reuse synthetic peripherals
    ext = resolve_extractor("microchip", "pic24f")
    payload = ext.extract(
        ExtractionRequest(
            vendor="microchip",
            family="pic24f",
            device="pic24fj128ga010",
            source_paths={"atdf": atdf},
            revision="r",
        )
    ).payload

    # PIC24F gets indirect pointers but never the dsPIC DSP carve-out.
    extensions = payload["arch_extensions"]
    assert "indirect_pointer_registers" in extensions
    assert "dsp_sfrs" not in extensions


_PIC32_ATDF = textwrap.dedent("""\
    <?xml version="1.0"?>
    <avr-tools-device-file>
      <devices>
        <device architecture="PIC32MX" family="PIC32MX" name="PIC32MX795F512L">
          <address-spaces>
            <address-space name="prog" id="prog" size="0x80000">
              <memory-segment name="KSEG0_PROGRAM_MEM" start="0x9D000000" size="0x80000" type="flash" rw="R"/>
            </address-space>
            <address-space name="cp0" id="cp0" size="0x100">
              <memory-segment name="STATUS"  start="0x0C" size="0x4" type="io" rw="RW"/>
              <memory-segment name="CAUSE"   start="0x0D" size="0x4" type="io" rw="RW"/>
              <memory-segment name="EBASE"   start="0x0F" size="0x4" type="io" rw="RW"/>
            </address-space>
          </address-spaces>
          <peripherals>
            <module name="UART">
              <instance name="UART1">
                <register-group name="UART1" address-space="prog" offset="0xBF806000"/>
              </instance>
            </module>
          </peripherals>
          <interrupts/>
        </device>
      </devices>
    </avr-tools-device-file>
""")


def test_pic32_projection_isolates_cp0_registers(tmp_path: Path) -> None:
    atdf = tmp_path / "PIC32MX795F512L.atdf"
    atdf.write_text(_PIC32_ATDF, encoding="utf-8")
    ext = resolve_extractor("microchip", "pic32mx")
    payload = ext.extract(
        ExtractionRequest(
            vendor="microchip",
            family="pic32mx",
            device="pic32mx795f512l",
            source_paths={"atdf": atdf},
            revision="r",
        )
    ).payload

    extensions = payload["arch_extensions"]
    cp0_names = {r["name"] for r in extensions["cp0_registers"]}
    assert cp0_names == {"STATUS", "CAUSE", "EBASE"}
    # CP0 registers must NOT show up in the regular peripherals list.
    assert "STATUS" not in {p["name"] for p in payload["peripherals"]}
    assert "UART1" in {p["name"] for p in payload["peripherals"]}


def test_pic18_arch_extensions_omitted_when_no_banked_segments(tmp_path: Path) -> None:
    atdf = tmp_path / "PIC18F47Q10.atdf"
    atdf.write_text(_ATDF_TEMPLATE.format(arch="PIC18", name="PIC18F47Q10"), encoding="utf-8")
    ext = resolve_extractor("microchip", "pic18")
    payload = ext.extract(
        ExtractionRequest(
            vendor="microchip",
            family="pic18",
            device="pic18f47q10",
            source_paths={"atdf": atdf},
            revision="r",
        )
    ).payload
    # Empty arch extensions are dropped from the payload entirely.
    assert "arch_extensions" not in payload
