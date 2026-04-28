"""Tests for the Zephyr DTS extractor.

Mirrors the alloy-codegen test surface — every vendor map
present, generic ARM-core compatibles unioned, parser walks
peripherals + interrupts + memories, end-to-end pipeline
writes a schema-valid YAML.
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

from alloy_data_extractor.extractors.zephyr_dts import (  # noqa: E402
    AMBIQ_COMPATIBLE_MAP,
    ATMEL_COMPATIBLE_MAP,
    COMPATIBLE_MAPS,
    ESPRESSIF_COMPATIBLE_MAP,
    INFINEON_COMPATIBLE_MAP,
    NORDIC_COMPATIBLE_MAP,
    RENESAS_RA_COMPATIBLE_MAP,
    SILABS_COMPATIBLE_MAP,
    TI_COMPATIBLE_MAP,
    compatible_map_for_vendor,
    extract_device,
    parse_zephyr_device_document,
)
from alloy_data_extractor.pipeline import (  # noqa: E402
    registered_extractors,
    run_extraction,
)


# ---------------------------------------------------------------------------
# Vendor coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vendor,vendor_map,must_have",
    [
        ("nordic", NORDIC_COMPATIBLE_MAP, "nordic,nrf-uart"),
        ("renesas", RENESAS_RA_COMPATIBLE_MAP, "renesas,ra-sci-uart"),
        ("ti", TI_COMPATIBLE_MAP, "ti,cc13xx-cc26xx-uart"),
        ("atmel", ATMEL_COMPATIBLE_MAP, "atmel,sam0-uart"),
        ("ambiq", AMBIQ_COMPATIBLE_MAP, "ambiq,uart"),
        ("infineon", INFINEON_COMPATIBLE_MAP, "infineon,xmc4xxx-uart"),
        ("silabs", SILABS_COMPATIBLE_MAP, "silabs,gecko-usart"),
        ("espressif", ESPRESSIF_COMPATIBLE_MAP, "espressif,esp32-uart"),
    ],
)
def test_every_vendor_map_includes_uart(vendor, vendor_map, must_have) -> None:
    """Every shipped vendor map must register at least its
    canonical UART binding."""
    assert vendor in COMPATIBLE_MAPS
    assert COMPATIBLE_MAPS[vendor] is vendor_map
    assert must_have in vendor_map


def test_compatible_map_for_vendor_unions_with_generic() -> None:
    """Spec scenario: ARM-core bindings (NVIC, SysTick) appear
    in every vendor's resolved map without per-vendor entries."""
    for vendor in COMPATIBLE_MAPS:
        merged = compatible_map_for_vendor(vendor)
        assert "arm,armv7m-nvic" in merged
        assert merged["arm,armv7m-nvic"] == "nvic"


def test_compatible_map_for_unknown_vendor_raises() -> None:
    with pytest.raises(ValueError, match="unknown vendor"):
        compatible_map_for_vendor("acme")


# ---------------------------------------------------------------------------
# DTS parsing
# ---------------------------------------------------------------------------


_SAMPLE_DTS = """
/dts-v1/;
/ {
    soc {
        compatible = "simple-bus";
        sram0: memory@20000000 {
            compatible = "mmio-sram";
            reg = <0x20000000 0x40000>;
        };
        uart0: uart@40002000 {
            compatible = "nordic,nrf-uart";
            reg = <0x40002000 0x1000>;
            interrupts = <2 1>;
        };
    };
};
"""


@pytest.fixture
def sample_dts(tmp_path: Path) -> Path:
    p = tmp_path / "fake.dts"
    p.write_text(textwrap.dedent(_SAMPLE_DTS).strip(), encoding="utf-8")
    return p


def test_parse_zephyr_device_document_extracts_peripherals_and_irqs(
    sample_dts: Path,
) -> None:
    doc = parse_zephyr_device_document(
        sample_dts, compatible_map=NORDIC_COMPATIBLE_MAP
    )
    assert any(p.name == "UART0" for p in doc.peripherals)
    assert any(i.line == 2 and i.peripheral == "UART0" for i in doc.interrupts)
    assert any(m.base_address == 0x20000000 for m in doc.memories)


def test_parse_skips_unknown_compatibles(tmp_path: Path) -> None:
    src = tmp_path / "exotic.dts"
    src.write_text(
        textwrap.dedent(
            """
            /dts-v1/;
            / {
                soc {
                    compatible = "simple-bus";
                    exotic: exotic@40000000 {
                        compatible = "renesas,future-thing";
                        reg = <0x40000000 0x1000>;
                    };
                };
            };
            """
        ).strip(),
        encoding="utf-8",
    )
    doc = parse_zephyr_device_document(src, compatible_map=NORDIC_COMPATIBLE_MAP)
    assert doc.peripherals == ()
    assert "renesas,future-thing" in doc.skipped_compatibles


# ---------------------------------------------------------------------------
# extract_device + pipeline registry
# ---------------------------------------------------------------------------


def test_extract_device_emits_canonical_payload(sample_dts: Path) -> None:
    extraction = extract_device(
        vendor="nordic",
        family="nrf52",
        device="nrf52840",
        svd_path=sample_dts,
        revision="abc123",
    )
    payload = extraction.payload
    assert payload["schema_version"] == "1.2.0"
    assert payload["identity"]["vendor"] == "nordic"
    assert payload["identity"]["device"] == "nrf52840"
    assert any(p["name"] == "UART0" for p in payload["peripherals"])
    assert extraction.provenance["source_id"] == "zephyr-dts"


def test_pipeline_registry_includes_zephyr_dts() -> None:
    assert "zephyr-dts" in registered_extractors()


def test_pipeline_writes_zephyr_dts_yaml(sample_dts: Path, tmp_path: Path) -> None:
    output = tmp_path / "data-repo"
    output.mkdir()
    results = run_extraction(
        vendor="nordic",
        family="nrf52",
        devices=["nrf52840"],
        extractor_id="zephyr-dts",
        source_paths={"nrf52840": sample_dts},
        output_root=output,
        revision="abc",
    )
    assert len(results) == 1
    written = results[0].yaml_path
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert text.startswith("schema_version:")
    assert "vendor: nordic" in text
