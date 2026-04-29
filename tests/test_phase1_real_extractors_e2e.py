"""End-to-end smoke tests for the implemented Phase-1
extractors (STM32, RP2040, NXP MCUX, ESP-IDF).

These tests load synthetic SVD data and confirm the extractor
produces a canonical-IR-shaped payload with the right
provenance.source_id stamp.  Real-device extraction needs
network-fetched cmsis-svd-data and is exercised by the parity
gate in alloy-codegen, not here.
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

from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor,
)

_MIN_SVD = textwrap.dedent("""\
    <?xml version="1.0"?>
    <device>
      <name>SYNTH</name>
      <description>Synthetic test device</description>
      <cpu>
        <name>CM0</name>
        <revision>r0p0</revision>
      </cpu>
      <peripherals>
        <peripheral>
          <name>UART0</name>
          <baseAddress>0x40010000</baseAddress>
          <description>UART0</description>
          <interrupt>
            <name>UART0_IRQ</name>
            <value>10</value>
          </interrupt>
        </peripheral>
      </peripherals>
    </device>
""")


@pytest.fixture
def synth_svd(tmp_path: Path) -> Path:
    p = tmp_path / "synth.svd"
    p.write_text(_MIN_SVD, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    ("vendor", "family", "device", "expected_source_id"),
    [
        ("st", "stm32g0", "stm32g071rb", "stm32"),
        ("raspberrypi", "rp2040", "rp2040", "pico-sdk"),
        ("nxp", "imxrt1060", "mimxrt1062", "nxp-mcux"),
        ("espressif", "esp32", "esp32", "esp-idf"),
        ("espressif", "esp32c3", "esp32c3", "esp-idf"),
        ("espressif", "esp32s3", "esp32s3", "esp-idf"),
        # Microchip uses ATDF instead of CMSIS-SVD — same synthetic
        # XML structure won't parse, so we exercise it separately.
    ],
)
def test_phase1_real_extractor_emits_canonical_payload(
    vendor: str,
    family: str,
    device: str,
    expected_source_id: str,
    synth_svd: Path,
) -> None:
    ext = resolve_extractor(vendor, family)
    request = ExtractionRequest(
        vendor=vendor,
        family=family,
        device=device,
        source_paths={"cmsis-svd": synth_svd},
        revision="rev-1.0.0",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["vendor"] == vendor
    assert result.payload["identity"]["family"] == family
    assert result.payload["identity"]["device"] == device
    assert result.payload["provenance"]["source_id"] == expected_source_id
    # Synthetic SVD declares one peripheral + one interrupt — both
    # must reach the canonical payload.
    assert any(p["name"] == "UART0" for p in result.payload["peripherals"])
    assert any(i["name"] == "UART0_IRQ" for i in result.payload["interrupts"])
    # Each Phase-1 implementation warns about deferred work.
    assert result.warnings, f"{expected_source_id} extractor should warn about deferred work"


@pytest.mark.parametrize(
    ("vendor", "family", "device"),
    [
        ("st", "stm32g0", "stm32g071rb"),
        ("raspberrypi", "rp2040", "rp2040"),
        ("nxp", "imxrt1060", "mimxrt1062"),
        ("espressif", "esp32", "esp32"),
        ("microchip", "same70", "atsame70q21b"),
    ],
)
def test_phase1_real_extractor_raises_value_error_when_no_source(
    vendor: str, family: str, device: str
) -> None:
    """Implemented extractors raise ValueError (not
    NotImplementedError) when their source path is missing —
    so callers see "you forgot --source <key>" rather than
    "this isn't built yet"."""
    ext = resolve_extractor(vendor, family)
    request = ExtractionRequest(
        vendor=vendor,
        family=family,
        device=device,
        source_paths={},
        revision="rev",
    )
    with pytest.raises(ValueError):
        ext.extract(request)


def test_nxp_mcux_per_row_provenance_uses_soc_svd_pin(synth_svd: Path) -> None:
    """`complete-imxrt1060-register-coverage`: every peripheral /
    register / register_field row's provenance source_id is the
    NXP source-pin id (`nxp-mcux-soc-svd`), not the generic
    `cmsis-svd` the shared walker stamps by default."""
    ext = resolve_extractor("nxp", "imxrt1060")
    request = ExtractionRequest(
        vendor="nxp",
        family="imxrt1060",
        device="mimxrt1062",
        source_paths={"cmsis-svd": synth_svd},
        revision="prov-test",
    )
    payload = ext.extract(request).payload
    # Top-level provenance still says "nxp-mcux" (the extractor id).
    assert payload["provenance"]["source_id"] == "nxp-mcux"
    # Per-row provenance is rewritten to the source-pin id.
    for row_field in ("peripherals", "interrupts"):
        for row in payload[row_field]:
            assert row["provenance"]["source_id"] == "nxp-mcux-soc-svd"


def test_microchip_dfp_extracts_synthetic_atdf(tmp_path: Path) -> None:
    """ATDF parser smoke test: feed a minimal ATDF and verify
    the extractor pulls peripherals + interrupts."""
    atdf_text = textwrap.dedent("""\
        <?xml version="1.0"?>
        <avr-tools-device-file>
          <devices>
            <device architecture="CORTEX-M7" family="SAME" name="ATSYNTH">
              <peripherals>
                <module name="UART">
                  <instance name="UART0">
                    <register-group name="UART0" address-space="base" offset="0x40010000"/>
                  </instance>
                </module>
              </peripherals>
              <interrupts>
                <interrupt index="10" name="UART0" module-instance="UART0"/>
              </interrupts>
            </device>
          </devices>
        </avr-tools-device-file>
    """)
    atdf_path = tmp_path / "ATSYNTH.atdf"
    atdf_path.write_text(atdf_text, encoding="utf-8")

    ext = resolve_extractor("microchip", "same70")
    request = ExtractionRequest(
        vendor="microchip",
        family="same70",
        device="atsynth",
        source_paths={"atdf": atdf_path},
        revision="rev",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["core"] == "cortex-m7"
    assert result.payload["provenance"]["source_id"] == "microchip-dfp"
    assert any(p["name"] == "UART0" for p in result.payload["peripherals"])
    assert any(i["line"] == 10 for i in result.payload["interrupts"])
