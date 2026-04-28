"""Smoke tests for the CMSIS-SVD extractor + canonical YAML
emitter.  Each new extractor adds a sibling test module here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.emit.canonical_yaml import serialize  # noqa: E402
from alloy_data_extractor.extractors.cmsis_svd import extract_device  # noqa: E402
from alloy_data_extractor.pipeline import (  # noqa: E402
    registered_extractors,
    run_extraction,
)

SAMPLE_SVD = """<?xml version="1.0"?>
<device>
  <name>FAKE</name>
  <description>Synthetic test device</description>
  <cpu>
    <name>CM4</name>
    <revision>r0p1</revision>
    <fpuPresent>true</fpuPresent>
  </cpu>
  <peripherals>
    <peripheral>
      <name>GPIOA</name>
      <baseAddress>0x40020000</baseAddress>
      <interrupt>
        <name>GPIOA_IRQ</name>
        <value>5</value>
      </interrupt>
    </peripheral>
    <peripheral>
      <name>USART1</name>
      <baseAddress>0x40011000</baseAddress>
      <interrupt>
        <name>USART1</name>
        <value>27</value>
      </interrupt>
    </peripheral>
  </peripherals>
</device>
"""


@pytest.fixture
def sample_svd(tmp_path: Path) -> Path:
    path = tmp_path / "fake.svd"
    path.write_text(SAMPLE_SVD, encoding="utf-8")
    return path


def test_extract_device_resolves_cm4f_core(sample_svd: Path) -> None:
    result = extract_device(
        vendor="acme",
        family="acme1",
        device="acme1xx",
        svd_path=sample_svd,
        revision="abc123",
    )
    assert result.payload["identity"]["core"] == "cortex-m4f"
    assert result.payload["identity"]["device"] == "acme1xx"
    assert result.payload["schema_version"] == "1.2.0"


def test_extract_device_includes_peripherals_and_interrupts(sample_svd: Path) -> None:
    result = extract_device(
        vendor="acme",
        family="acme1",
        device="acme1xx",
        svd_path=sample_svd,
        revision="abc",
    )
    names = {p["name"] for p in result.payload["peripherals"]}
    assert "GPIOA" in names and "USART1" in names
    irq_lines = sorted(i["line"] for i in result.payload["interrupts"])
    assert irq_lines == [5, 27]


def test_serialize_produces_top_level_canonical_order(sample_svd: Path) -> None:
    """schema_version must be first, identity second, provenance third."""
    result = extract_device(
        vendor="acme",
        family="acme1",
        device="acme1xx",
        svd_path=sample_svd,
        revision="abc",
    )
    text = serialize(result.payload)
    top_keys = [
        line.split(":", 1)[0] for line in text.splitlines() if line and not line.startswith(" ")
    ]
    assert top_keys[:3] == ["schema_version", "identity", "provenance"]


def test_pipeline_writes_yaml_to_output_root(sample_svd: Path, tmp_path: Path) -> None:
    output = tmp_path / "data-repo"
    output.mkdir()
    results = run_extraction(
        vendor="acme",
        family="acme1",
        devices=["acme1xx"],
        extractor_id="cmsis-svd",
        source_paths={"acme1xx": sample_svd},
        output_root=output,
        revision="abc123",
    )
    assert len(results) == 1
    written = results[0].yaml_path
    assert written.exists()
    assert written == output / "vendors/acme/acme1/devices/acme1xx.yml"
    assert written.read_text(encoding="utf-8").startswith("schema_version:")


def test_registered_extractors_lists_cmsis_svd() -> None:
    assert "cmsis-svd" in registered_extractors()


def test_unknown_extractor_id_raises(sample_svd: Path, tmp_path: Path) -> None:
    output = tmp_path / "data-repo"
    output.mkdir()
    with pytest.raises(ValueError, match="unknown extractor_id"):
        run_extraction(
            vendor="acme",
            family="acme1",
            devices=["acme1xx"],
            extractor_id="nonexistent",
            source_paths={"acme1xx": sample_svd},
            output_root=output,
            revision="abc",
        )
