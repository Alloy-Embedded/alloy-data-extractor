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
    registers, _, _ = _register_and_field_records(root)
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
    registers, _, _ = _register_and_field_records(root)
    by_peri = {r["peripheral"] for r in registers}
    assert {"USART1", "USART2"}.issubset(by_peri)
    usart2_regs = [r for r in registers if r["peripheral"] == "USART2"]
    # USART2 mirrors USART1's CR1 / BRR / DR0..3 → 6 registers.
    assert len(usart2_regs) == 6


def test_register_field_records_use_canonical_field_id(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_register_tree_svd(tmp_path)).getroot()
    _, fields, _ = _register_and_field_records(root)
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


# ---------------------------------------------------------------------------
# Per-row provenance stamping
# ---------------------------------------------------------------------------


def test_peripheral_rows_carry_per_row_provenance(sample_svd: Path) -> None:
    """Every peripheral row stamps a `provenance` block with the
    SVD basename + the supplied source_id.  Reviewers can audit
    which SVD file produced each row, even after merging."""
    result = extract_device(
        vendor="acme",
        family="acme1",
        device="acme1xx",
        svd_path=sample_svd,
        revision="abc",
    )
    for peri in result.payload["peripherals"]:
        assert peri["provenance"]["source_id"] == "cmsis-svd"
        assert peri["provenance"]["source_path"] == "fake.svd"
        assert peri["provenance"]["patch_ids"] == []
    for interrupt in result.payload["interrupts"]:
        assert interrupt["provenance"]["source_id"] == "cmsis-svd"
        assert interrupt["provenance"]["source_path"] == "fake.svd"


def test_register_rows_carry_per_row_provenance(tmp_path: Path) -> None:
    """Each register + register_field row carries a per-row
    provenance block referencing the SVD basename."""
    import xml.etree.ElementTree as ET

    root = ET.parse(_register_tree_svd(tmp_path)).getroot()
    registers, fields, _ = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="rt.svd"
    )
    for reg in registers:
        assert reg["provenance"] == {
            "source_id": "cmsis-svd",
            "source_path": "rt.svd",
            "patch_ids": [],
        }
    for fld in fields:
        assert fld["provenance"]["source_id"] == "cmsis-svd"
        assert fld["provenance"]["source_path"] == "rt.svd"
        assert fld["provenance"]["patch_ids"] == []


# ---------------------------------------------------------------------------
# register_field_enumerations (complete-stm32-tier-coverage Phase 1)
# ---------------------------------------------------------------------------


def _enum_svd(tmp_path: Path) -> Path:
    """SVD covering: basic enum + multi-block (read+write usage) +
    derivedFrom (peripheral-relative + bare-field forms) + an
    enum on a derived peripheral that propagates through."""
    text = textwrap.dedent("""\
        <?xml version="1.0"?>
        <device>
          <name>EN</name>
          <peripherals>
            <peripheral>
              <name>ADC1</name>
              <baseAddress>0x40012400</baseAddress>
              <size>32</size>
              <access>read-write</access>
              <registers>
                <register>
                  <name>CFGR1</name>
                  <addressOffset>0x0C</addressOffset>
                  <fields>
                    <field>
                      <name>RES</name>
                      <bitOffset>3</bitOffset>
                      <bitWidth>2</bitWidth>
                      <enumeratedValues>
                        <usage>read-write</usage>
                        <enumeratedValue>
                          <name>BITS12</name>
                          <description>12-bit resolution</description>
                          <value>0</value>
                        </enumeratedValue>
                        <enumeratedValue>
                          <name>BITS10</name>
                          <description>10-bit resolution</description>
                          <value>1</value>
                        </enumeratedValue>
                        <enumeratedValue>
                          <name>BITS8</name>
                          <description>8-bit resolution</description>
                          <value>2</value>
                        </enumeratedValue>
                        <enumeratedValue>
                          <name>BITS6</name>
                          <description>6-bit resolution</description>
                          <value>3</value>
                        </enumeratedValue>
                      </enumeratedValues>
                    </field>
                    <field>
                      <name>EXTSEL</name>
                      <bitOffset>6</bitOffset>
                      <bitWidth>3</bitWidth>
                      <enumeratedValues>
                        <usage>read</usage>
                        <enumeratedValue>
                          <name>READ_TIM1_TRGO</name>
                          <value>0</value>
                        </enumeratedValue>
                      </enumeratedValues>
                      <enumeratedValues>
                        <usage>write</usage>
                        <enumeratedValue>
                          <name>WRITE_TIM1_TRGO</name>
                          <value>0</value>
                        </enumeratedValue>
                      </enumeratedValues>
                    </field>
                  </fields>
                </register>
                <register>
                  <name>SMPR1</name>
                  <addressOffset>0x14</addressOffset>
                  <fields>
                    <field>
                      <name>SMP1</name>
                      <bitOffset>0</bitOffset>
                      <bitWidth>3</bitWidth>
                      <enumeratedValues>
                        <enumeratedValue>
                          <name>CYCLES_2_5</name>
                          <value>0</value>
                        </enumeratedValue>
                        <enumeratedValue>
                          <name>CYCLES_6_5</name>
                          <value>1</value>
                        </enumeratedValue>
                      </enumeratedValues>
                    </field>
                    <field>
                      <name>SMP2</name>
                      <bitOffset>3</bitOffset>
                      <bitWidth>3</bitWidth>
                      <enumeratedValues derivedFrom="SMPR1.SMP1"/>
                    </field>
                    <field>
                      <name>SMP3</name>
                      <bitOffset>6</bitOffset>
                      <bitWidth>3</bitWidth>
                      <enumeratedValues derivedFrom="SMP1"/>
                    </field>
                  </fields>
                </register>
              </registers>
            </peripheral>
            <peripheral derivedFrom="ADC1">
              <name>ADC2</name>
              <baseAddress>0x40012800</baseAddress>
            </peripheral>
          </peripherals>
        </device>
    """)
    path = tmp_path / "en.svd"
    path.write_text(text, encoding="utf-8")
    return path


def test_enumerations_concrete_values_extracted(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, enums = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    res_rows = [e for e in enums if e["field_id"] == "field:adc1:cfgr1:res"]
    assert len(res_rows) == 4
    by_value = {e["raw_value"]: e for e in res_rows}
    assert by_value[0]["name"] == "BITS12"
    assert by_value[0]["description"] == "12-bit resolution"
    assert by_value[0]["usage"] == "read-write"
    assert by_value[3]["name"] == "BITS6"


def test_enumerations_honor_read_vs_write_usage(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, enums = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    extsel_rows = [e for e in enums if e["field_id"] == "field:adc1:cfgr1:extsel"]
    by_usage = {e["usage"]: e for e in extsel_rows}
    assert "read" in by_usage and "write" in by_usage
    assert by_usage["read"]["name"] == "READ_TIM1_TRGO"
    assert by_usage["write"]["name"] == "WRITE_TIM1_TRGO"


def test_enumerations_derived_from_relative_path_resolves(tmp_path: Path) -> None:
    """`<enumeratedValues derivedFrom="SMPR1.SMP1"/>` on a sibling
    field within the same peripheral SHALL pick up the base
    field's row set."""
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, enums = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    smp2_rows = [e for e in enums if e["field_id"] == "field:adc1:smpr1:smp2"]
    assert len(smp2_rows) == 2
    by_value = {e["raw_value"]: e for e in smp2_rows}
    assert by_value[0]["name"] == "CYCLES_2_5"
    assert by_value[1]["name"] == "CYCLES_6_5"


def test_enumerations_derived_from_bare_name_falls_back(tmp_path: Path) -> None:
    """`<enumeratedValues derivedFrom="SMP1"/>` (bare field name)
    SHALL resolve via the by-name fallback index."""
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, enums = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    smp3_rows = [e for e in enums if e["field_id"] == "field:adc1:smpr1:smp3"]
    assert len(smp3_rows) == 2
    by_value = {e["raw_value"]: e for e in smp3_rows}
    assert by_value[0]["name"] == "CYCLES_2_5"


def test_enumerations_propagate_via_derivedFrom_peripheral(tmp_path: Path) -> None:
    """ADC2 derivedFrom ADC1 inherits the entire register tree —
    the enumerations SHALL appear under both peripherals'
    field_ids."""
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, enums = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    field_ids = {e["field_id"] for e in enums}
    assert "field:adc1:cfgr1:res" in field_ids
    assert "field:adc2:cfgr1:res" in field_ids


def test_enumeration_rows_carry_per_row_provenance(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, enums = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    for row in enums:
        assert row["provenance"] == {
            "source_id": "cmsis-svd",
            "source_path": "en.svd",
            "patch_ids": [],
        }


def test_extract_device_includes_register_field_enumerations(sample_svd: Path) -> None:
    """End-to-end: the canonical payload includes the new
    top-level `register_field_enumerations` array even when the
    fixture SVD ships no enums (empty list, key present)."""
    result = extract_device(
        vendor="acme",
        family="acme1",
        device="acme1xx",
        svd_path=sample_svd,
        revision="abc",
    )
    assert "register_field_enumerations" in result.payload
    assert result.payload["register_field_enumerations"] == []


def test_enumerations_sorted_deterministically(tmp_path: Path) -> None:
    """Rows SHALL be sorted by (field_id, usage, raw_value) for
    byte-stable YAML output across runs."""
    import xml.etree.ElementTree as ET

    root = ET.parse(_enum_svd(tmp_path)).getroot()
    _, _, run1 = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    _, _, run2 = _register_and_field_records(
        root, source_id="cmsis-svd", source_path="en.svd"
    )
    assert run1 == run2
    keys = [(e["field_id"], e["usage"], e["raw_value"]) for e in run1]
    assert keys == sorted(keys)
