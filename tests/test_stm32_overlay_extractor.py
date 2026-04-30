"""Tests for the STM32 family-overlay extractor + I2C TIMINGR
helper (`complete-stm32-tier-coverage` Phases 5-6).
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
    resolve_extractor_by_id,
)
from alloy_data_extractor.extractors.stm32_i2c_timing import (  # noqa: E402
    I2cTimingPreset,
    compute_i2c_timing_preset,
    compute_i2c_timing_presets_for_speeds_and_clocks,
)
from alloy_data_extractor.extractors.stm32_overlay import (  # noqa: E402
    _project_overlay,
    _resolve_overlay,
)


# ---------------------------------------------------------------------------
# Phase 5 — TOML loading + projection
# ---------------------------------------------------------------------------


def _build_synthetic_overlay(tmp_path: Path) -> Path:
    """Lay out a minimal overlay tree at <tmp>/data/vendors/st/..."""
    root = tmp_path / "data" / "vendors" / "st"
    family_dir = root / "stm32fx" / "devices"
    family_dir.mkdir(parents=True)
    (root / "stm32fx" / "family.toml").write_text(
        textwrap.dedent("""\
            [adc]
            max_clock_hz = 50_000_000

            [adc.calibration_context]
            peripheral = "ADC1"
            vrefint_nominal_mv = 1200
            cal_voltage_mv = 3300
            cal_temp_low_celsius = 25
            cal_temp_high_celsius = 110

            [[adc.calibration_data_points]]
            peripheral = "ADC1"
            kind = "ts_cal_low"
            address = 0x1FFF7000
            size_bits = 16
            semantic_constant = 25

            [[adc.internal_channels]]
            peripheral = "ADC1"
            kind = "vrefint"
            channel_index = 17

            [i2c]
            max_clock_hz = 1_000_000
            [[i2c.speed_options]]
            name = "standard"
            speed_hz = 100_000

            [system_clock.post_reset_profile]
            name = "default-hsi-16mhz"
            sysclk_hz = 16_000_000
            hclk_hz = 16_000_000
            pclk_hz = 16_000_000
            source = "HSI"
        """),
        encoding="utf-8",
    )
    (family_dir / "stm32fx_outlier.toml").write_text(
        textwrap.dedent("""\
            [adc]
            max_clock_hz = 60_000_000  # per-device override

            [[adc.calibration_data_points]]
            peripheral = "ADC1"
            kind = "ts_cal_low"
            address = 0x1FFF8000  # different from family default
            size_bits = 16
            semantic_constant = 25
        """),
        encoding="utf-8",
    )
    return root


def test_resolve_overlay_loads_family_toml(tmp_path: Path) -> None:
    root = _build_synthetic_overlay(tmp_path)
    data, paths = _resolve_overlay(family="stm32fx", device="stm32fx_basic", overlay_root=root)
    assert data["adc"]["max_clock_hz"] == 50_000_000
    # Out-of-tree overlay roots fall back to filename for the
    # provenance path (in-repo overlays use the repo-relative form).
    assert paths == ["family.toml"]


def test_resolve_overlay_per_device_override_wins(tmp_path: Path) -> None:
    """Per-device TOML SHALL replace family-default values."""
    root = _build_synthetic_overlay(tmp_path)
    data, paths = _resolve_overlay(
        family="stm32fx", device="stm32fx_outlier", overlay_root=root
    )
    assert data["adc"]["max_clock_hz"] == 60_000_000  # device wins
    # family layer also contributed (vrefint_nominal_mv survives)
    assert data["adc"]["calibration_context"]["vrefint_nominal_mv"] == 1200
    assert paths == ["family.toml", "stm32fx_outlier.toml"]


def test_resolve_overlay_missing_files_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "data" / "vendors" / "st"
    root.mkdir(parents=True)
    data, paths = _resolve_overlay(family="stm32xx", device="stm32xx99", overlay_root=root)
    assert data == {}
    assert paths == []


def test_project_overlay_emits_canonical_fields(tmp_path: Path) -> None:
    root = _build_synthetic_overlay(tmp_path)
    data, _ = _resolve_overlay(family="stm32fx", device="stm32fx_basic", overlay_root=root)
    payload = _project_overlay(
        data, source_path="family.toml", revision="rev-1"
    )
    assert payload["adc_max_clock_hz"] == 50_000_000
    assert payload["adc_calibration_context"]["vrefint_nominal_mv"] == 1200
    # Provenance stamped on every projected row.
    cal_rows = payload["adc_calibration_data_points"]
    assert len(cal_rows) == 1
    assert cal_rows[0]["provenance"]["source_id"] == "stm32-overlay"
    assert cal_rows[0]["provenance"]["source_path"] == "family.toml"
    # Internal channels.
    assert payload["adc_internal_channels"][0]["kind"] == "vrefint"
    # I2C speed_options moved to stm32-tier (per-instance fan-out
    # needs the CubeMX peripheral list); overlay no longer emits.
    assert "i2c_speed_options" not in payload
    # System clock profiles carry canonical SystemClockProfile shape.
    profiles = payload["system_clock_profiles"]
    assert profiles[0]["kind"] == "post-reset"
    assert profiles[0]["profile_id"] == "default-hsi-16mhz"
    assert profiles[0]["source_kind"] == "HSI"


def test_extractor_resolves_real_stm32g0_overlay() -> None:
    """End-to-end: the bundled stm32g0/family.toml projects 8
    canonical fields for stm32g071rb."""
    ext = resolve_extractor_by_id("stm32-overlay")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={},
        revision="real-test",
    )
    payload = ext.extract(request).payload
    assert payload["adc_max_clock_hz"] == 35_000_000
    assert len(payload["adc_calibration_data_points"]) == 3
    assert len(payload["adc_internal_channels"]) == 3
    assert {r["kind"] for r in payload["adc_internal_channels"]} == {
        "vrefint",
        "temperature_sensor",
        "vbat",
    }
    assert payload["uart_max_baud_hz"] == 4_000_000
    assert payload["i2c_max_clock_hz"] == 1_000_000
    # i2c_speed_options moved to stm32-tier — no longer in
    # overlay output.
    assert "i2c_speed_options" not in payload


def test_extractor_does_not_win_resolver() -> None:
    """`stm32-overlay` is secondary — must not auto-resolve."""
    ext = resolve_extractor("st", "stm32g0")
    assert ext.extractor_id == "stm32"


def test_extractor_warns_when_no_overlay_present(tmp_path: Path) -> None:
    """A device without an overlay TOML SHALL produce an empty
    payload + a warning (not raise)."""
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    ext = resolve_extractor_by_id("stm32-overlay")
    request = ExtractionRequest(
        vendor="st",
        family="stm32xx",  # no TOML at this family
        device="stm32xx99",
        source_paths={"stm32-overlay-root": empty_root},
        revision="r",
    )
    result = ext.extract(request)
    # Warning surface (not raise).
    assert result.warnings
    assert "no TOML at" in result.warnings[0]


# ---------------------------------------------------------------------------
# Phase 6 — I2C TIMINGR computation
# ---------------------------------------------------------------------------


def test_compute_i2c_timing_preset_basic_shape() -> None:
    preset = compute_i2c_timing_preset(speed_hz=100_000, source_clock_hz=64_000_000)
    assert isinstance(preset, I2cTimingPreset)
    assert preset.speed_hz == 100_000
    assert preset.source_clock_hz == 64_000_000
    # Field bit-width invariants — TIMINGR layout.
    assert 0 <= preset.presc <= 0xF
    assert 0 <= preset.sdadel <= 0xF
    assert 0 <= preset.scldel <= 0xF
    assert 0 <= preset.sclh <= 0xFF
    assert 0 <= preset.scll <= 0xFF


@pytest.mark.parametrize("speed_hz", [100_000, 400_000, 1_000_000])
def test_compute_i2c_timing_preset_per_standard_speed(speed_hz: int) -> None:
    preset = compute_i2c_timing_preset(
        speed_hz=speed_hz, source_clock_hz=64_000_000
    )
    # The TIMINGR pack returns a sane integer.
    timingr = preset.timingr_value
    assert 0 < timingr < 2**32


def test_compute_i2c_timing_preset_is_deterministic() -> None:
    a = compute_i2c_timing_preset(speed_hz=400_000, source_clock_hz=48_000_000)
    b = compute_i2c_timing_preset(speed_hz=400_000, source_clock_hz=48_000_000)
    assert a == b


def test_compute_i2c_timing_preset_rejects_unsupported_speed() -> None:
    with pytest.raises(ValueError, match="unsupported speed"):
        compute_i2c_timing_preset(speed_hz=50_000, source_clock_hz=64_000_000)


def test_compute_i2c_timing_preset_rejects_zero_source_clock() -> None:
    with pytest.raises(ValueError, match="source_clock_hz must be > 0"):
        compute_i2c_timing_preset(speed_hz=100_000, source_clock_hz=0)


def test_compute_i2c_timing_presets_cross_product() -> None:
    presets = compute_i2c_timing_presets_for_speeds_and_clocks(
        speeds_hz=[100_000, 400_000, 1_000_000],
        source_clocks_hz=[16_000_000, 64_000_000],
    )
    # 3 speeds × 2 clocks = 6 presets.
    assert len(presets) == 6
    # Sorted by (speed, source_clock).
    keys = [(p.speed_hz, p.source_clock_hz) for p in presets]
    assert keys == sorted(keys)


def test_overlay_emits_i2c_timing_presets_when_speeds_and_profiles_present(
    tmp_path: Path,
) -> None:
    """The overlay extractor SHALL compute i2c_timing_presets
    automatically from i2c.speed_options × system_clock_profiles."""
    root = _build_synthetic_overlay(tmp_path)
    ext = resolve_extractor_by_id("stm32-overlay")
    request = ExtractionRequest(
        vendor="st",
        family="stm32fx",
        device="stm32fx_basic",
        source_paths={"stm32-overlay-root": root},
        revision="r",
    )
    payload = ext.extract(request).payload
    # i2c_timing_presets only emit when CubeMX is staged so the
    # overlay can fan out per-instance.  This synthetic-overlay
    # path has no CubeMX — presets stay empty.
    assert payload.get("i2c_timing_presets", []) == []


def test_overlay_real_stm32g0_emits_i2c_timing_cross_product() -> None:
    """When stm32cubemx-db is staged, the overlay fans out
    timing presets per I2C instance × speeds × sysclks.
    stm32g071rb has I2C1+I2C2 (2) × 3 speeds × 2 sysclks = 12 rows."""
    cubemx_db = Path(
        "/Applications/STMicroelectronics/STM32CubeMX.app/Contents/Resources/db"
    )
    if not cubemx_db.exists():
        pytest.skip(f"STM32CubeMX not installed at {cubemx_db}")
    ext = resolve_extractor_by_id("stm32-overlay")
    request = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"stm32cubemx-db": cubemx_db},
        revision="r",
    )
    payload = ext.extract(request).payload
    presets = payload.get("i2c_timing_presets", [])
    assert len(presets) == 12  # 2 instances × 3 speeds × 2 sysclks
    instances = {p["peripheral"] for p in presets}
    assert instances == {"I2C1", "I2C2"}
