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


# ---------------------------------------------------------------------------
# Register-tree projection (cmsis_svd._register_and_field_records)
# ---------------------------------------------------------------------------

import textwrap  # noqa: E402

from alloy_data_extractor.extractors.cmsis_svd import (  # noqa: E402
    _expand_register_dim,
    _parse_dim_index,
    _parse_field_position,
    _register_and_field_records,
)


def _register_tree_svd(tmp_path: Path) -> Path:
    text = textwrap.dedent("""\
        <?xml version="1.0"?>
        <device>
          <name>RT</name>
          <peripherals>
            <peripheral>
              <name>USART1</name>
              <baseAddress>0x40011000</baseAddress>
              <size>32</size>
              <access>read-write</access>
              <registers>
                <register>
                  <name>CR1</name>
                  <addressOffset>0x00</addressOffset>
                  <size>32</size>
                  <fields>
                    <field>
                      <name>UE</name>
                      <bitOffset>0</bitOffset>
                      <bitWidth>1</bitWidth>
                    </field>
                    <field>
                      <name>WAKE</name>
                      <bitRange>[11:11]</bitRange>
                    </field>
                    <field>
                      <name>SR</name>
                      <lsb>4</lsb>
                      <msb>5</msb>
                      <access>read-only</access>
                    </field>
                  </fields>
                </register>
                <register>
                  <name>BRR</name>
                  <addressOffset>0x0C</addressOffset>
                </register>
                <register>
                  <dim>4</dim>
                  <dimIncrement>4</dimIncrement>
                  <dimIndex>0,1,2,3</dimIndex>
                  <name>DR%s</name>
                  <addressOffset>0x20</addressOffset>
                </register>
              </registers>
            </peripheral>
            <peripheral derivedFrom="USART1">
              <name>USART2</name>
              <baseAddress>0x40004400</baseAddress>
            </peripheral>
          </peripherals>
        </device>
    """)
    path = tmp_path / "rt.svd"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_field_position_handles_three_legal_forms() -> None:
    import xml.etree.ElementTree as ET

    f1 = ET.fromstring("<field><bitOffset>3</bitOffset><bitWidth>5</bitWidth></field>")
    assert _parse_field_position(f1) == (3, 5)
    f2 = ET.fromstring("<field><bitRange>[15:8]</bitRange></field>")
    assert _parse_field_position(f2) == (8, 8)
    f3 = ET.fromstring("<field><lsb>4</lsb><msb>7</msb></field>")
    assert _parse_field_position(f3) == (4, 4)
    f4 = ET.fromstring("<field><name>X</name></field>")
    assert _parse_field_position(f4) == (None, None)


def test_parse_dim_index_handles_range_and_csv_forms() -> None:
    assert _parse_dim_index("0-3", 4) == ["0", "1", "2", "3"]
    assert _parse_dim_index("A,B,C", 3) == ["A", "B", "C"]
    assert _parse_dim_index(None, 3) == ["0", "1", "2"]


def test_expand_register_dim_yields_one_row_when_dim_absent() -> None:
    import xml.etree.ElementTree as ET

    reg = ET.fromstring(
        "<register><name>CR1</name><addressOffset>0x4</addressOffset></register>"
    )
    rows = _expand_register_dim(reg)
    assert len(rows) == 1
    assert rows[0]["name"] == "CR1"
    assert rows[0]["offset"] == 4


def test_expand_register_dim_substitutes_index_into_name() -> None:
    import xml.etree.ElementTree as ET

    reg = ET.fromstring(
        "<register>"
        "<dim>4</dim><dimIncrement>4</dimIncrement><dimIndex>0,1,2,3</dimIndex>"
        "<name>DR%s</name><addressOffset>0x20</addressOffset>"
        "</register>"
    )
    rows = _expand_register_dim(reg)
    assert [r["name"] for r in rows] == ["DR0", "DR1", "DR2", "DR3"]
    assert [r["offset"] for r in rows] == [0x20, 0x24, 0x28, 0x2C]


def test_register_records_emit_canonical_register_id_keys(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_register_tree_svd(tmp_path)).getroot()
    registers, _ = _register_and_field_records(root)
    by_id = {r["register_id"]: r for r in registers}
    assert "register:usart1:cr1" in by_id
    assert "register:usart1:brr" in by_id
    assert "register:usart1:dr0" in by_id
    assert by_id["register:usart1:cr1"]["offset_bytes"] == 0x00
    assert by_id["register:usart1:brr"]["offset_bytes"] == 0x0C
    # Default size + access inherit from peripheral.
    assert by_id["register:usart1:brr"]["size_bits"] == 32
    assert by_id["register:usart1:brr"]["access"] == "read-write"


def test_register_records_resolve_derived_from(tmp_path: Path) -> None:
    """USART2 derivedFrom USART1 inherits the entire register tree."""
    import xml.etree.ElementTree as ET

    root = ET.parse(_register_tree_svd(tmp_path)).getroot()
    registers, _ = _register_and_field_records(root)
    by_peri = {r["peripheral"] for r in registers}
    assert {"USART1", "USART2"}.issubset(by_peri)
    usart2_regs = [r for r in registers if r["peripheral"] == "USART2"]
    # USART2 mirrors USART1's CR1 / BRR / DR0..3 → 6 registers.
    assert len(usart2_regs) == 6


def test_register_field_records_use_canonical_field_id(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_register_tree_svd(tmp_path)).getroot()
    _, fields = _register_and_field_records(root)
    by_id = {f["field_id"]: f for f in fields}
    assert "field:usart1:cr1:ue" in by_id
    assert by_id["field:usart1:cr1:ue"]["bit_offset"] == 0
    assert by_id["field:usart1:cr1:ue"]["bit_width"] == 1
    # bitRange-form field.
    assert by_id["field:usart1:cr1:wake"]["bit_offset"] == 11
    assert by_id["field:usart1:cr1:wake"]["bit_width"] == 1
    # lsb/msb-form field with explicit access override.
    assert by_id["field:usart1:cr1:sr"]["bit_offset"] == 4
    assert by_id["field:usart1:cr1:sr"]["bit_width"] == 2
    assert by_id["field:usart1:cr1:sr"]["access"] == "read-only"


def test_extract_device_now_carries_register_tree(sample_svd: Path) -> None:
    """The plain extract_device path includes registers + register_fields."""
    result = extract_device(
        vendor="acme",
        family="acme1",
        device="acme1xx",
        svd_path=sample_svd,
        revision="abc",
    )
    assert "registers" in result.payload
    assert "register_fields" in result.payload
    # The fixture SVD has no <registers> blocks, so the lists are
    # empty — but the keys exist so consumers (merge engine, etc.)
    # can rely on their presence.
    assert result.payload["registers"] == []
    assert result.payload["register_fields"] == []
