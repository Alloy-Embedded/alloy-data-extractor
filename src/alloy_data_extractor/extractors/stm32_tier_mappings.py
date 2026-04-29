"""Per-IP-version tier-2/3/4 mapping tables for STM32 peripherals.

`complete-stm32-tier-coverage` Phase 2 (canonical-shape rewrite).

Each mapping table encodes the canonical (semantic, raw)
projection rows for one CubeMX IP version (e.g. ``sci3_v2_1_Cube``
for the STM32G0 USART).  Rows are produced **per peripheral
instance** — so USART1 and USART2 emit independent
``uart_data_bits_options`` rows tagged with their instance
names, matching the canonical alloy-devices-yml shape.

The (semantic, raw) values are silicon facts: shared by every ST
chip using the IP version.  Adding a new STM32 chip in an
already-supported family becomes "stage SVD + CubeMX entry" with
zero edits to this module.

Schema of a row produced by these projection functions matches
the canonical YAML's tier arrays exactly (see
``docs/stm32-tier-pipeline.md``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


# A projection function takes the instance name (e.g. "USART1")
# and returns the list of canonical-shape rows for that instance.
ProjectionFn = Callable[[str], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class TierProjection:
    """One canonical tier-array projection for an instance."""

    target_field: str
    project: ProjectionFn


@dataclass(frozen=True, slots=True)
class TierMapping:
    """Per-IP-version → list of per-instance projections."""

    ip_name: str
    ip_version_pattern: re.Pattern[str]
    projections: tuple[TierProjection, ...]


# ===========================================================================
# USART
# ===========================================================================

# Canonical shapes per family.
def _usart_v3_data_bits(instance: str) -> list[dict[str, Any]]:
    return [
        {"peripheral": instance, "bits": 7, "m0_value": 0, "m1_value": 1},
        {"peripheral": instance, "bits": 8, "m0_value": 0, "m1_value": 0},
        {"peripheral": instance, "bits": 9, "m0_value": 1, "m1_value": 0},
    ]


def _usart_v2_data_bits(instance: str) -> list[dict[str, Any]]:
    return [
        {"peripheral": instance, "bits": 8, "m0_value": 0, "m1_value": 0},
        {"peripheral": instance, "bits": 9, "m0_value": 1, "m1_value": 0},
    ]


def _usart_parity(instance: str) -> list[dict[str, Any]]:
    return [
        {"peripheral": instance, "parity": "none", "pce_value": 0, "ps_value": 0},
        {"peripheral": instance, "parity": "even", "pce_value": 1, "ps_value": 0},
        {"peripheral": instance, "parity": "odd", "pce_value": 1, "ps_value": 1},
    ]


def _usart_stop_bits(instance: str) -> list[dict[str, Any]]:
    # Canonical encodes stop bits as Q8 fixed-point (×256).
    return [
        {"peripheral": instance, "stop_bits_q8": 128, "field_value": 1},  # 0.5
        {"peripheral": instance, "stop_bits_q8": 256, "field_value": 0},  # 1
        {"peripheral": instance, "stop_bits_q8": 384, "field_value": 3},  # 1.5
        {"peripheral": instance, "stop_bits_q8": 512, "field_value": 2},  # 2
    ]


def _usart_v3_mode_flags(instance: str) -> list[dict[str, Any]]:
    return [
        {
            "peripheral": instance,
            "supports_lin": True,
            "supports_irda": True,
            "supports_smartcard": True,
            "supports_half_duplex": True,
        }
    ]


def _usart_v2_mode_flags(instance: str) -> list[dict[str, Any]]:
    return [
        {
            "peripheral": instance,
            "supports_lin": True,
            "supports_irda": True,
            "supports_smartcard": True,
            "supports_half_duplex": True,
        }
    ]


USART_SCI3_V2_TIER = TierMapping(
    ip_name="USART",
    ip_version_pattern=re.compile(r"^sci3_v2_\d+_Cube$"),
    projections=(
        TierProjection("uart_data_bits_options", _usart_v3_data_bits),
        TierProjection("uart_parity_options", _usart_parity),
        TierProjection("uart_stop_bits_options", _usart_stop_bits),
        TierProjection("uart_mode_flags", _usart_v3_mode_flags),
    ),
)


USART_SCI2_V1_TIER = TierMapping(
    ip_name="USART",
    ip_version_pattern=re.compile(r"^sci2_v\d+_\d+_Cube$"),
    projections=(
        TierProjection("uart_data_bits_options", _usart_v2_data_bits),
        TierProjection("uart_parity_options", _usart_parity),
        TierProjection("uart_stop_bits_options", _usart_stop_bits),
        TierProjection("uart_mode_flags", _usart_v2_mode_flags),
    ),
)


# ===========================================================================
# SPI
# ===========================================================================


def _spi_baud_prescaler(instance: str) -> list[dict[str, Any]]:
    # CR1.BR — 8 prescaler values (f_pclk/2 .. f_pclk/256).
    return [
        {"peripheral": instance, "divisor": 2 ** (i + 1), "field_value": i}
        for i in range(8)
    ]


def _spi_v3_mode_flags(instance: str) -> list[dict[str, Any]]:
    # G0 / F4 SPI v3 surface — modern STM32 SPI with TI frame mode.
    return [
        {
            "peripheral": instance,
            "supports_crc": True,
            "supports_ti_frame": True,
            "supports_motorola_frame": True,
            "supports_i2s_submode": False,
            "supports_bidirectional_3wire": True,
            "supports_lsb_first": True,
            "supports_nss_hw_management": True,
        }
    ]


def _spi_v2_mode_flags(instance: str) -> list[dict[str, Any]]:
    # F4 SPI v2 — TI frame mode is gated by I2S sub-mode availability;
    # otherwise comparable surface.
    return [
        {
            "peripheral": instance,
            "supports_crc": True,
            "supports_ti_frame": True,
            "supports_motorola_frame": True,
            "supports_i2s_submode": True,  # F4 SPIs share the I2S engine
            "supports_bidirectional_3wire": True,
            "supports_lsb_first": True,
            "supports_nss_hw_management": True,
        }
    ]


SPI_V3_TIER = TierMapping(
    ip_name="SPI",
    ip_version_pattern=re.compile(r"^spi2s1_v3_\d+_Cube$"),
    projections=(
        TierProjection("spi_baud_prescaler_options", _spi_baud_prescaler),
        TierProjection("spi_mode_flags", _spi_v3_mode_flags),
    ),
)


SPI_V2_TIER = TierMapping(
    ip_name="SPI",
    ip_version_pattern=re.compile(r"^spi2s1_v2_\d+_Cube$"),
    projections=(
        TierProjection("spi_baud_prescaler_options", _spi_baud_prescaler),
        TierProjection("spi_mode_flags", _spi_v2_mode_flags),
    ),
)


# ===========================================================================
# I2C
# ===========================================================================


def _i2c_v1_mode_flags(instance: str) -> list[dict[str, Any]]:
    return [
        {
            "peripheral": instance,
            "supports_smbus": True,
            "supports_pmbus": False,
            "supports_dma": True,
            "supports_slave": True,
        }
    ]


def _i2c_f4_mode_flags(instance: str) -> list[dict[str, Any]]:
    # F4's older i2c1 IP — same surface for the 4 canonical flags.
    return [
        {
            "peripheral": instance,
            "supports_smbus": True,
            "supports_pmbus": False,
            "supports_dma": True,
            "supports_slave": True,
        }
    ]


def _i2c_v1_speed_options(instance: str) -> list[dict[str, Any]]:
    # G0's i2c2_v1 — supports the full 100k / 400k / 1M trio.
    return [
        {"peripheral": instance, "speed_hz": 100_000, "mode": "standard"},
        {"peripheral": instance, "speed_hz": 400_000, "mode": "fast"},
        {"peripheral": instance, "speed_hz": 1_000_000, "mode": "fast_plus"},
    ]


def _i2c_f4_speed_options(instance: str) -> list[dict[str, Any]]:
    # F4's i2c1 — no fast-plus.
    return [
        {"peripheral": instance, "speed_hz": 100_000, "mode": "standard"},
        {"peripheral": instance, "speed_hz": 400_000, "mode": "fast"},
    ]


I2C_V1_TIER = TierMapping(
    ip_name="I2C",
    ip_version_pattern=re.compile(r"^i2c2_v\d+_\d+_Cube$"),
    projections=(
        TierProjection("i2c_mode_flags", _i2c_v1_mode_flags),
        TierProjection("i2c_speed_options", _i2c_v1_speed_options),
    ),
)


I2C_F4_TIER = TierMapping(
    ip_name="I2C",
    ip_version_pattern=re.compile(r"^i2c1_v\d+_\d+_Cube$"),
    projections=(
        TierProjection("i2c_mode_flags", _i2c_f4_mode_flags),
        TierProjection("i2c_speed_options", _i2c_f4_speed_options),
    ),
)


# ===========================================================================
# ADC
# ===========================================================================


def _adc_resolution(instance: str) -> list[dict[str, Any]]:
    # Universal across modern STM32 ADCs (12/10/8/6 bits).
    return [
        {"peripheral": instance, "bits": 12, "field_value": 0},
        {"peripheral": instance, "bits": 10, "field_value": 1},
        {"peripheral": instance, "bits": 8, "field_value": 2},
        {"peripheral": instance, "bits": 6, "field_value": 3},
    ]


def _adc_g0_sample_time(instance: str) -> list[dict[str, Any]]:
    # G0 sample-time encoding (cycles_q8 = cycles × 256).
    pairs = [
        ("1.5", 0, 384),
        ("3.5", 1, 896),
        ("7.5", 2, 1920),
        ("12.5", 3, 3200),
        ("19.5", 4, 4992),
        ("39.5", 5, 10112),
        ("79.5", 6, 20352),
        ("160.5", 7, 41088),
    ]
    return [
        {"peripheral": instance, "cycles_q8": q8, "field_value": fv}
        for _, fv, q8 in pairs
    ]


def _adc_f4_sample_time(instance: str) -> list[dict[str, Any]]:
    # F4 sample-time encoding (cycles_q8 = integer cycles × 256).
    pairs = [(3, 0), (15, 1), (28, 2), (56, 3), (84, 4), (112, 5), (144, 6), (480, 7)]
    return [
        {"peripheral": instance, "cycles_q8": cycles * 256, "field_value": fv}
        for cycles, fv in pairs
    ]


def _adc_g0_oversampling(instance: str) -> list[dict[str, Any]]:
    # G0 supports 2..256× oversampling (8 ratios).
    return [
        {"peripheral": instance, "ratio": 2 ** (i + 1), "field_value": i}
        for i in range(8)
    ]


def _adc_g0_external_triggers(instance: str) -> list[dict[str, Any]]:
    # G0 ADC EXTSEL — names lowercased to match canonical convention.
    triggers = [
        ("tim1_trgo2", 0),
        ("tim1_cc4", 1),
        ("tim2_trgo", 2),
        ("tim3_trgo", 3),
        ("tim15_trgo", 4),
        ("tim6_trgo", 5),
        ("exti11", 7),
    ]
    return [
        {
            "peripheral": instance,
            "source": source,
            "extsel_value": fv,
            "default_polarity": 1,
        }
        for source, fv in triggers
    ]


def _adc_f4_external_triggers(instance: str) -> list[dict[str, Any]]:
    # F4 EXTSEL is 4 bits (16 sources) — RM0090 §13.13.4.
    triggers = [
        ("tim1_cc1", 0),
        ("tim1_cc2", 1),
        ("tim1_cc3", 2),
        ("tim2_cc2", 3),
        ("tim2_cc3", 4),
        ("tim2_cc4", 5),
        ("tim2_trgo", 6),
        ("tim3_cc1", 7),
        ("tim3_trgo", 8),
        ("tim4_cc4", 9),
        ("tim5_cc1", 10),
        ("tim5_cc2", 11),
        ("tim5_cc3", 12),
        ("tim8_cc1", 13),
        ("tim8_trgo", 14),
        ("exti11", 15),
    ]
    return [
        {
            "peripheral": instance,
            "source": source,
            "extsel_value": fv,
            "default_polarity": 1,
        }
        for source, fv in triggers
    ]


ADC_G0_V3_TIER = TierMapping(
    ip_name="ADC",
    ip_version_pattern=re.compile(r"^aditf4_v3_\d+_G0_Cube$"),
    projections=(
        TierProjection("adc_resolution_options", _adc_resolution),
        TierProjection("adc_sample_time_options", _adc_g0_sample_time),
        TierProjection("adc_oversampling_options", _adc_g0_oversampling),
        TierProjection("adc_external_triggers", _adc_g0_external_triggers),
    ),
)


ADC_F4_V1_TIER = TierMapping(
    ip_name="ADC",
    ip_version_pattern=re.compile(r"^aditf2_v\d+_\d+_Cube$"),
    projections=(
        TierProjection("adc_resolution_options", _adc_resolution),
        TierProjection("adc_sample_time_options", _adc_f4_sample_time),
        # F4 silicon has no oversampling (hardware fact).
        TierProjection("adc_external_triggers", _adc_f4_external_triggers),
    ),
)


# ===========================================================================
# Timer (general + advanced share the IP version on G0 / F4)
# ===========================================================================


def _timer_prescaler(instance: str) -> list[dict[str, Any]]:
    # max_prescaler always 65535 (16-bit PSC); max_auto_reload is
    # 32-bit on TIM2 (G0 + F4) and TIM5 (F4), 16-bit elsewhere.
    arr_max = (
        0xFFFFFFFF if instance in {"TIM2", "TIM5"} else 0xFFFF
    )
    return [
        {
            "peripheral": instance,
            "max_prescaler": 0xFFFF,
            "max_auto_reload": arr_max,
        }
    ]


_TIMER_TRIGGER_NAMES = (
    ("itr0", 0b000),
    ("itr1", 0b001),
    ("itr2", 0b010),
    ("itr3", 0b011),
    ("ti1f_ed", 0b100),
    ("ti1fp1", 0b101),
    ("ti2fp2", 0b110),
    ("etrf", 0b111),
)


def _timer_trigger_sources(instance: str) -> list[dict[str, Any]]:
    return [
        {"peripheral": instance, "source": name, "field_value": fv}
        for name, fv in _TIMER_TRIGGER_NAMES
    ]


_TIMER_MASTER_OUTPUT_NAMES = (
    ("reset", 0b000),
    ("enable", 0b001),
    ("update", 0b010),
    ("compare_pulse", 0b011),
    ("oc1ref", 0b100),
    ("oc2ref", 0b101),
    ("oc3ref", 0b110),
    ("oc4ref", 0b111),
)


def _timer_master_outputs(instance: str) -> list[dict[str, Any]]:
    return [
        {"peripheral": instance, "source": name, "field_value": fv}
        for name, fv in _TIMER_MASTER_OUTPUT_NAMES
    ]


_TIMER_ADVANCED_INSTANCES = frozenset(
    {"TIM1", "TIM8", "TIM15", "TIM16", "TIM17"}
)


def _timer_mode_flags(instance: str) -> list[dict[str, Any]]:
    is_advanced = instance in _TIMER_ADVANCED_INSTANCES
    return [
        {
            "peripheral": instance,
            "supports_dma_burst": True,
            "supports_repetition_counter": is_advanced,
            "supports_xor_input": True,
        }
    ]


_PWM_ALIGNMENTS = (
    ("edge", 0),
    ("center_down", 1),
    ("center_up", 2),
    ("center_up_down", 3),
)


def _pwm_alignment_options(instance: str) -> list[dict[str, Any]]:
    return [
        {"peripheral": instance, "alignment": name, "field_value": fv}
        for name, fv in _PWM_ALIGNMENTS
    ]


def _pwm_break_inputs(instance: str) -> list[dict[str, Any]]:
    if instance not in _TIMER_ADVANCED_INSTANCES:
        return []  # GP timers don't have BDTR
    rows = [
        {
            "peripheral": instance,
            "input_id": "bkin",
            "polarity_field_value": 0,
            "enable_field_value": 1,
        }
    ]
    if instance in {"TIM1", "TIM8"}:
        # TIM1/TIM8 (G0 + F4) carry BK2 too.
        rows.append(
            {
                "peripheral": instance,
                "input_id": "bkin2",
                "polarity_field_value": 0,
                "enable_field_value": 1,
            }
        )
    return rows


def _pwm_deadtime_options(instance: str) -> list[dict[str, Any]]:
    if instance not in _TIMER_ADVANCED_INSTANCES:
        return []
    # BDTR.DTG 4-range encoding — canonical shape per range.
    # max_ns assumes a representative t_DTS of 10 ns; real chip
    # value depends on prescaler at runtime — codegen renders
    # symbolically.
    return [
        {
            "peripheral": instance,
            "prescaler_field_value": 0,
            "count_bits": 7,
            "max_ns": 1270,
        },
        {
            "peripheral": instance,
            "prescaler_field_value": 1,
            "count_bits": 6,
            "max_ns": 2540,
        },
        {
            "peripheral": instance,
            "prescaler_field_value": 2,
            "count_bits": 5,
            "max_ns": 5040,
        },
        {
            "peripheral": instance,
            "prescaler_field_value": 3,
            "count_bits": 5,
            "max_ns": 10080,
        },
    ]


def _pwm_mode_flags(instance: str) -> list[dict[str, Any]]:
    is_advanced = instance in _TIMER_ADVANCED_INSTANCES
    return [
        {
            "peripheral": instance,
            "supports_deadtime": is_advanced,
            "supports_break_input": is_advanced,
            "supports_complementary_outputs": instance in {"TIM1", "TIM8"},
            "supports_asymmetric_pwm": True,
        }
    ]


# Both G0 (gptimer2_v3_x_Cube) and F4 (gptimer2_v2_x_Cube) share
# the SVD-level register fields covered by these projections.
TIMER_GPTIMER_V3_TIER = TierMapping(
    ip_name="TIM1_8G0",
    ip_version_pattern=re.compile(r"^gptimer2_v3_\w+_Cube$"),
    projections=(
        TierProjection("timer_prescaler_options", _timer_prescaler),
        TierProjection("timer_trigger_sources", _timer_trigger_sources),
        TierProjection("timer_master_outputs", _timer_master_outputs),
        TierProjection("timer_mode_flags", _timer_mode_flags),
        TierProjection("pwm_alignment_options", _pwm_alignment_options),
        TierProjection("pwm_break_inputs", _pwm_break_inputs),
        TierProjection("pwm_deadtime_options", _pwm_deadtime_options),
        TierProjection("pwm_mode_flags", _pwm_mode_flags),
    ),
)


TIMER_F4_GPTIMER_V2_TIER = TierMapping(
    ip_name="TIM1_8",
    ip_version_pattern=re.compile(r"^gptimer2_v2_\w+_Cube$"),
    projections=(
        TierProjection("timer_prescaler_options", _timer_prescaler),
        TierProjection("timer_trigger_sources", _timer_trigger_sources),
        TierProjection("timer_master_outputs", _timer_master_outputs),
        TierProjection("timer_mode_flags", _timer_mode_flags),
        TierProjection("pwm_alignment_options", _pwm_alignment_options),
        TierProjection("pwm_break_inputs", _pwm_break_inputs),
        TierProjection("pwm_deadtime_options", _pwm_deadtime_options),
        TierProjection("pwm_mode_flags", _pwm_mode_flags),
    ),
)


# ===========================================================================
# Registry
# ===========================================================================


ALL_TIER_MAPPINGS: tuple[TierMapping, ...] = (
    USART_SCI3_V2_TIER,
    USART_SCI2_V1_TIER,
    SPI_V3_TIER,
    SPI_V2_TIER,
    I2C_V1_TIER,
    I2C_F4_TIER,
    ADC_G0_V3_TIER,
    ADC_F4_V1_TIER,
    TIMER_GPTIMER_V3_TIER,
    TIMER_F4_GPTIMER_V2_TIER,
)


def find_tier_mapping(ip_name: str, ip_version: str) -> TierMapping | None:
    """Return the first TierMapping whose ``ip_name`` AND
    ``ip_version_pattern`` both match.

    ``ip_name`` filtering matters for IP-version namespaces ST
    shares between distinct hardware kinds — e.g. SPI and I2S
    on STM32G0 both report ``Version="spi2s1_v3_*_Cube"``,
    differentiated only by ``Name="SPI"`` vs ``Name="I2S"``.
    Without the name filter, an I2S1 instance would incorrectly
    pick up SPI tier projections.

    ``ip_name`` is matched by exact string for now.  Mappings
    with ``ip_name="TIM1_8G0"`` etc. cover the CubeMX-specific
    naming variants.
    """
    for mapping in ALL_TIER_MAPPINGS:
        if mapping.ip_name and mapping.ip_name != ip_name:
            continue
        if mapping.ip_version_pattern.match(ip_version):
            return mapping
    return None


__all__ = [
    "ADC_F4_V1_TIER",
    "ADC_G0_V3_TIER",
    "ALL_TIER_MAPPINGS",
    "I2C_F4_TIER",
    "I2C_V1_TIER",
    "SPI_V2_TIER",
    "SPI_V3_TIER",
    "TIMER_F4_GPTIMER_V2_TIER",
    "TIMER_GPTIMER_V3_TIER",
    "TierMapping",
    "TierProjection",
    "USART_SCI2_V1_TIER",
    "USART_SCI3_V2_TIER",
    "find_tier_mapping",
]
