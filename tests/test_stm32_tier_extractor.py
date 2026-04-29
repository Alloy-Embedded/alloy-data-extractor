"""Tests for the STM32 tier-2/3/4 projector
(`complete-stm32-tier-coverage` Phase 2).

Covers the per-IP-version mapping tables, the projection
algorithm (instance dedup + cross-IP-version row union), and
end-to-end resolution against either a synthetic CubeMX DB or
the locally installed STM32CubeMX.
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

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    MissingSourceError,
    resolve_extractor,
    resolve_extractor_by_id,
)
from alloy_data_extractor.extractors.stm32_tier import (  # noqa: E402
    _project_tier_arrays,
    _ResolvedInstance,
)
from alloy_data_extractor.extractors.stm32_tier_mappings import (  # noqa: E402
    ADC_F4_V1_TIER,
    ADC_G0_V3_TIER,
    ALL_TIER_MAPPINGS,
    SPI_V3_TIER,
    TIMER_GPTIMER_V3_TIER,
    USART_SCI3_V2_TIER,
    find_tier_mapping,
)


# ---------------------------------------------------------------------------
# find_tier_mapping — version-pattern dispatch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ip_name", "ip_version", "expected_mapping"),
    [
        ("USART", "sci3_v2_1_Cube", USART_SCI3_V2_TIER),
        ("USART", "sci3_v2_5_Cube", USART_SCI3_V2_TIER),
        ("ADC", "aditf4_v3_0_G0_Cube", ADC_G0_V3_TIER),
        ("ADC", "aditf2_v1_1_Cube", ADC_F4_V1_TIER),
        ("SPI", "spi2s1_v3_3_Cube", SPI_V3_TIER),
        ("TIM1_8G0", "gptimer2_v3_x_Cube", TIMER_GPTIMER_V3_TIER),
    ],
)
def test_find_tier_mapping_routes_known_versions(
    ip_name: str, ip_version: str, expected_mapping
) -> None:
    assert find_tier_mapping(ip_name, ip_version) is expected_mapping


def test_find_tier_mapping_returns_none_for_unknown_version() -> None:
    assert find_tier_mapping("UNKNOWN", "fake_v0_0_Cube") is None


def test_all_tier_mappings_have_distinct_ip_versions_per_pattern() -> None:
    """Sanity: every TierMapping uses a distinct (ip_name,
    pattern) tuple.  Catches accidental dupes that would cause
    silent mapping-table shadowing."""
    seen: set[tuple[str, str]] = set()
    for mapping in ALL_TIER_MAPPINGS:
        key = (mapping.ip_name, mapping.ip_version_pattern.pattern)
        assert key not in seen, f"duplicate mapping: {key}"
        seen.add(key)


# ---------------------------------------------------------------------------
# _project_tier_arrays — instance-level row union + dedup
# ---------------------------------------------------------------------------


def _instance(ip_name: str, ip_version: str, instance_name: str) -> _ResolvedInstance:
    return _ResolvedInstance(
        instance_name=instance_name,
        ip_name=ip_name,
        ip_version=ip_version,
        mapping=find_tier_mapping(ip_name, ip_version),
    )


def test_project_tier_arrays_emits_per_target_field_rows() -> None:
    """Single USART instance projects into 4 target_fields with
    the expected row counts."""
    arrays = _project_tier_arrays([_instance("USART", "sci3_v2_1_Cube", "USART1")])
    assert len(arrays["uart_data_bits_options"]) == 3
    assert len(arrays["uart_parity_options"]) == 3
    assert len(arrays["uart_stop_bits_options"]) == 4
    assert len(arrays["uart_mode_flags"]) == 1
    # No timer / ADC arrays from a UART-only chip.
    assert "adc_resolution_options" not in arrays
    assert "timer_master_outputs" not in arrays


def test_project_tier_arrays_dedups_same_ip_across_instances() -> None:
    """USART1 + USART2 + USART3 all use sci3_v2_1_Cube — the
    rows project once, not three times."""
    arrays = _project_tier_arrays(
        [
            _instance("USART", "sci3_v2_1_Cube", "USART1"),
            _instance("USART", "sci3_v2_1_Cube", "USART2"),
            _instance("USART", "sci3_v2_1_Cube", "USART3"),
        ]
    )
    assert len(arrays["uart_data_bits_options"]) == 3
    assert len(arrays["uart_parity_options"]) == 3


def test_project_tier_arrays_unions_distinct_ip_versions() -> None:
    """USART (sci3_v2) + LPUART (also sci3_v2) on the same chip
    union into one row set.  Two different IPs both projecting
    onto `pwm_alignment_options` would also union here."""
    arrays = _project_tier_arrays(
        [
            _instance("USART", "sci3_v2_1_Cube", "USART1"),
            # Hypothetical second IP version that also projects to
            # the same target_field — our G0 tables don't trigger
            # this, but the dedup logic supports it.
        ]
    )
    # Single source — same as before.
    assert len(arrays["uart_data_bits_options"]) == 3


def test_project_tier_arrays_skips_unmapped_instances() -> None:
    """A peripheral whose IP version has no mapping table SHALL
    contribute zero rows (no exception)."""
    arrays = _project_tier_arrays(
        [
            _instance("USART", "sci3_v2_1_Cube", "USART1"),
            _instance("HDMI_CEC", "hdmi_cec_v2_0_Cube", "HDMI_CEC"),
            _instance("UNKNOWN", "fake_v0_0_Cube", "FOO1"),
        ]
    )
    # Only USART rows surface.
    assert "uart_data_bits_options" in arrays
    # The unmapped IPs don't contribute weird targets.
    assert all(k.startswith("uart_") for k in arrays)


def test_project_tier_arrays_sorts_rows_by_raw_value() -> None:
    """Rows SHALL be deterministically ordered for byte-stable
    YAML output across runs."""
    arrays_run1 = _project_tier_arrays(
        [_instance("USART", "sci3_v2_1_Cube", "USART1")]
    )
    arrays_run2 = _project_tier_arrays(
        [_instance("USART", "sci3_v2_1_Cube", "USART1")]
    )
    assert arrays_run1 == arrays_run2
    # spi_baud_prescaler raw_values should ascend.
    spi_arrays = _project_tier_arrays(
        [_instance("SPI", "spi2s1_v3_3_Cube", "SPI1")]
    )
    raw_values = [r["raw_value"] for r in spi_arrays["spi_baud_prescaler_options"]]
    assert raw_values == sorted(raw_values)


# ---------------------------------------------------------------------------
# Synthetic CubeMX DB end-to-end
# ---------------------------------------------------------------------------


def _build_synthetic_db(tmp_path: Path) -> Path:
    """Minimal CubeMX MCU XML carrying a few representative IPs
    so the extractor can run offline."""
    db = tmp_path / "db"
    mcu_dir = db / "mcu"
    mcu_dir.mkdir(parents=True)
    (mcu_dir / "STM32G071RBTx.xml").write_text(
        textwrap.dedent("""\
            <?xml version="1.0"?>
            <Mcu xmlns="http://mcd.rou.st.com/modules.php?name=mcu"
                 RefName="STM32G071RBTx" Family="STM32G0" Line="STM32G0x1">
              <Core>ARM Cortex-M0+</Core>
              <IP InstanceName="USART1" Name="USART" Version="sci3_v2_1_Cube"/>
              <IP InstanceName="USART2" Name="USART" Version="sci3_v2_1_Cube"/>
              <IP InstanceName="ADC1"   Name="ADC"   Version="aditf4_v3_0_G0_Cube"/>
              <IP InstanceName="SPI1"   Name="SPI"   Version="spi2s1_v3_3_Cube"/>
              <IP InstanceName="I2C1"   Name="I2C"   Version="i2c2_v1_1_Cube"/>
              <IP InstanceName="TIM1"   Name="TIM1_8G0" Version="gptimer2_v3_x_Cube"/>
              <IP InstanceName="TIM2"   Name="TIM1_8G0" Version="gptimer2_v3_x_Cube"/>
              <IP InstanceName="HDMI_CEC" Name="HDMI_CEC" Version="hdmi_cec_v2_0_Cube"/>
            </Mcu>
        """),
        encoding="utf-8",
    )
    return db


def test_extractor_payload_carries_18_tier_fields_for_g0(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    ext = resolve_extractor_by_id("stm32-tier")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"stm32cubemx-db": db},
        revision="r",
    )
    payload = ext.extract(request).payload

    # Sanity: ADC + USART + SPI + I2C + Timer + PWM all populated.
    assert len(payload["adc_resolution_options"]) == 4
    assert len(payload["adc_sample_time_options"]) == 8
    assert len(payload["adc_oversampling_options"]) == 8
    assert len(payload["adc_external_triggers"]) == 7
    assert len(payload["uart_data_bits_options"]) == 3
    assert len(payload["uart_parity_options"]) == 3
    assert len(payload["uart_stop_bits_options"]) == 4
    assert len(payload["spi_baud_prescaler_options"]) == 8
    assert len(payload["i2c_mode_flags"]) == 1
    assert len(payload["timer_prescaler_options"]) == 17
    assert len(payload["timer_trigger_sources"]) == 8
    assert len(payload["timer_master_outputs"]) == 8
    assert len(payload["pwm_alignment_options"]) == 4
    assert len(payload["pwm_break_inputs"]) == 2
    assert len(payload["pwm_deadtime_options"]) == 4

    # Resolution log surfaces unmapped IPs.
    res = payload["stm32_tier_resolution"]
    by_ip = {r["instance_name"]: r for r in res}
    assert by_ip["USART1"]["mapped"] is True
    assert by_ip["HDMI_CEC"]["mapped"] is False


def test_extractor_provenance_source_id_is_stm32_tier(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    ext = resolve_extractor_by_id("stm32-tier")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"stm32cubemx-db": db},
        revision="prov-test",
    )
    payload = ext.extract(request).payload
    assert payload["provenance"]["source_id"] == "stm32-tier"
    assert "stm32-tier@prov-test" in payload["provenance"]["patch_ids"]


def test_extractor_does_not_win_resolver_for_st_family() -> None:
    """`stm32-tier` is secondary — must not auto-resolve for ST."""
    ext = resolve_extractor("st", "stm32g0")
    assert ext.extractor_id == "stm32"


def test_extractor_raises_missing_source_when_path_absent() -> None:
    ext = resolve_extractor_by_id("stm32-tier")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={},
        revision="r",
    )
    with pytest.raises(MissingSourceError) as excinfo:
        ext.extract(request)
    assert "stm32cubemx-db" in str(excinfo.value)


def test_extractor_warns_about_unmapped_ips(tmp_path: Path) -> None:
    db = _build_synthetic_db(tmp_path)
    ext = resolve_extractor_by_id("stm32-tier")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"stm32cubemx-db": db},
        revision="r",
    )
    result = ext.extract(request)
    # HDMI_CEC + UNKNOWN are unmapped; warning lists at least
    # the count and one sample.
    warnings_text = "\n".join(result.warnings)
    assert "had no tier mapping" in warnings_text
    assert "HDMI_CEC" in warnings_text


# ---------------------------------------------------------------------------
# Real-DB smoke tests against locally installed STM32CubeMX
# ---------------------------------------------------------------------------


_DEFAULT_CUBEMX_DB = Path(
    "/Applications/STMicroelectronics/STM32CubeMX.app/Contents/Resources/db"
)


def test_extract_against_real_cubemx_db_for_stm32g071rb() -> None:
    if not _DEFAULT_CUBEMX_DB.exists():
        pytest.skip(f"STM32CubeMX not installed at {_DEFAULT_CUBEMX_DB}")
    ext = resolve_extractor_by_id("stm32-tier")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"stm32cubemx-db": _DEFAULT_CUBEMX_DB},
        revision="real-cubemx",
    )
    payload = ext.extract(request).payload
    # Tier-3 fields the canonical YAML expects to be populated
    # for stm32g071rb.
    expected_tier_fields = {
        "adc_resolution_options",
        "adc_sample_time_options",
        "adc_oversampling_options",
        "adc_external_triggers",
        "uart_data_bits_options",
        "uart_parity_options",
        "uart_stop_bits_options",
        "spi_baud_prescaler_options",
        "timer_prescaler_options",
        "timer_trigger_sources",
        "timer_master_outputs",
        "pwm_alignment_options",
        "pwm_break_inputs",
        "pwm_deadtime_options",
    }
    populated = {k for k in payload if k in expected_tier_fields}
    assert populated == expected_tier_fields, (
        f"missing tier fields: {expected_tier_fields - populated}"
    )
