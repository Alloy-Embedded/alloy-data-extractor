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
