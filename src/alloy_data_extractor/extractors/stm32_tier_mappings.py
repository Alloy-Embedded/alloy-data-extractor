"""Per-IP-version tier-2/3/4 mapping tables for STM32 peripherals.

`complete-stm32-tier-coverage` Phase 2.2.

Each mapping table encodes the canonical (human_value, raw_value)
pairs for one CubeMX IP version (e.g. ``sci3_v2_1_Cube`` for the
STM32G0 USART).  These pairs are universal across every ST chip
sharing that IP version — they're a function of silicon design,
not a per-chip fact.  Adding a new STM32 chip in an
already-supported family becomes "stage SVD + CubeMX entry; run
bulk extract" without touching this module.

CMSIS-SVD ``<enumeratedValues>`` would in principle let us
project these tables off the SVD instead of hardcoding them.  In
practice the cmsis-svd-data community SVDs have wildly uneven
enum coverage — STM32G071's SVD has enums for ADC + TIM15 only;
STM32F405's SVD has zero enums.  Hardcoded tables per-IP-version
deliver tier-3 deterministically regardless of SVD richness.

Schema of an entry:

* ``ip_name`` matches the CubeMX ``<IP Name="…">`` attribute.
* ``ip_version_pattern`` matches the ``<IP Version="…">`` string.
* ``projections`` lists per-target-field row sets.  Rows are
  written as canonical-IR-shaped dicts.

The projector (`stm32_tier.py`) walks every CubeMX-discovered
peripheral, looks up the matching entry, and emits one
canonical row set per ``target_field`` per chip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TierProjection:
    """One tier-2/3/4 array projection.

    ``rows`` is rendered verbatim as the corresponding payload
    field's value.  When two projections target the same
    ``target_field`` (e.g. multiple IP versions on the same chip),
    the projector unions the row sets with deduplication on the
    ``raw_value``-bearing key.
    """

    target_field: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class TierMapping:
    """One CubeMX IP version → list of canonical-tier projections."""

    ip_name: str
    ip_version_pattern: re.Pattern[str]
    projections: tuple[TierProjection, ...]


# ---------------------------------------------------------------------------
# USART — STM32G0 (sci3_v2_x_Cube), STM32F4 (sci2_v1_x_Cube)
# ---------------------------------------------------------------------------

# Universal across modern ST USART (sci3_v2_*).  M0 + M1 encode
# 5/6/7/8/9 data bits.  STM32F4 (sci2_v1_*) lacks the 7-bit mode
# but otherwise mirrors the encoding.
_USART_V3_DATA_BITS_ROWS: tuple[dict[str, Any], ...] = (
    {"value_bits": 7, "raw_m0": 0, "raw_m1": 1},
    {"value_bits": 8, "raw_m0": 0, "raw_m1": 0},
    {"value_bits": 9, "raw_m0": 1, "raw_m1": 0},
)
_USART_V2_DATA_BITS_ROWS: tuple[dict[str, Any], ...] = (
    {"value_bits": 8, "raw_m0": 0, "raw_m1": 0},
    {"value_bits": 9, "raw_m0": 1, "raw_m1": 0},
)
_USART_PARITY_ROWS: tuple[dict[str, Any], ...] = (
    {"parity": "none", "raw_pce": 0, "raw_ps": 0},
    {"parity": "even", "raw_pce": 1, "raw_ps": 0},
    {"parity": "odd", "raw_pce": 1, "raw_ps": 1},
)
_USART_STOP_BITS_ROWS: tuple[dict[str, Any], ...] = (
    {"value": "0.5", "raw_value": 0b01},
    {"value": "1", "raw_value": 0b00},
    {"value": "1.5", "raw_value": 0b11},
    {"value": "2", "raw_value": 0b10},
)
_USART_MODE_FLAGS_ROWS: tuple[dict[str, Any], ...] = (
    {
        "supports_synchronous": True,
        "supports_smartcard": True,
        "supports_irda": True,
        "supports_lin": True,
        "supports_modbus": True,
        "supports_auto_baud": True,  # sci3 only — F4 sci2 lacks this
    },
)

USART_SCI3_V2_TIER = TierMapping(
    ip_name="USART",
    ip_version_pattern=re.compile(r"^sci3_v2_\d+_Cube$"),
    projections=(
        TierProjection("uart_data_bits_options", _USART_V3_DATA_BITS_ROWS),
        TierProjection("uart_parity_options", _USART_PARITY_ROWS),
        TierProjection("uart_stop_bits_options", _USART_STOP_BITS_ROWS),
        TierProjection("uart_mode_flags", _USART_MODE_FLAGS_ROWS),
    ),
)

USART_SCI2_V1_TIER = TierMapping(
    ip_name="USART",
    ip_version_pattern=re.compile(r"^sci2_v\d+_\d+_Cube$"),
    projections=(
        TierProjection("uart_data_bits_options", _USART_V2_DATA_BITS_ROWS),
        TierProjection("uart_parity_options", _USART_PARITY_ROWS),
        TierProjection("uart_stop_bits_options", _USART_STOP_BITS_ROWS),
    ),
)


# ---------------------------------------------------------------------------
# SPI — STM32G0 / F4 (spi2s1_v3_x_Cube)
# ---------------------------------------------------------------------------

# CR1.BR encodes 8 prescaler values (f_pclk/2 .. f_pclk/256).
_SPI_BAUD_PRESCALER_ROWS: tuple[dict[str, Any], ...] = tuple(
    {"value_divisor": 2 ** (i + 1), "raw_value": i} for i in range(8)
)

SPI_V3_TIER = TierMapping(
    ip_name="SPI",
    ip_version_pattern=re.compile(r"^spi2s1_v3_\d+_Cube$"),
    projections=(
        TierProjection("spi_baud_prescaler_options", _SPI_BAUD_PRESCALER_ROWS),
    ),
)

# STM32F4 SPI uses spi2s1_v2_x_Cube — same BR encoding (8 prescalers).
SPI_V2_TIER = TierMapping(
    ip_name="SPI",
    ip_version_pattern=re.compile(r"^spi2s1_v2_\d+_Cube$"),
    projections=(
        TierProjection("spi_baud_prescaler_options", _SPI_BAUD_PRESCALER_ROWS),
    ),
)


# ---------------------------------------------------------------------------
# I2C — STM32G0 (i2c2_v1_1_Cube)
# ---------------------------------------------------------------------------

# i2c.speed_options are universal (100k / 400k / 1M); the family
# overlay TOML provides the per-family max_clock_hz.  Mode flags
# encode hardware-supported modes on this IP.
_I2C_MODE_FLAGS_ROWS: tuple[dict[str, Any], ...] = (
    {
        "supports_smbus": True,
        "supports_pec": True,
        "supports_dnf": True,
        "supports_clock_stretching": True,
        "supports_wakeup_from_stop": True,
    },
)

I2C_V1_TIER = TierMapping(
    ip_name="I2C",
    ip_version_pattern=re.compile(r"^i2c2_v\d+_\d+_Cube$"),
    projections=(TierProjection("i2c_mode_flags", _I2C_MODE_FLAGS_ROWS),),
)

# STM32F4 I2C — older `i2c1_v1_x_Cube` IP.  No fast-plus, no
# clock-stretching wakeup; otherwise comparable surface.
_I2C_F4_MODE_FLAGS_ROWS: tuple[dict[str, Any], ...] = (
    {
        "supports_smbus": True,
        "supports_pec": True,
        "supports_dnf": False,  # F4 has analog filter only
        "supports_clock_stretching": True,
        "supports_wakeup_from_stop": False,
    },
)

I2C_F4_TIER = TierMapping(
    ip_name="I2C",
    ip_version_pattern=re.compile(r"^i2c1_v\d+_\d+_Cube$"),
    projections=(TierProjection("i2c_mode_flags", _I2C_F4_MODE_FLAGS_ROWS),),
)


# ---------------------------------------------------------------------------
# ADC — STM32G0 (aditf4_v3_0_G0_Cube)
# ---------------------------------------------------------------------------

# ADC_CFGR1.RES — 12 / 10 / 8 / 6 bit resolution.
_ADC_G0_RESOLUTION_ROWS: tuple[dict[str, Any], ...] = (
    {"value_bits": 12, "raw_value": 0},
    {"value_bits": 10, "raw_value": 1},
    {"value_bits": 8, "raw_value": 2},
    {"value_bits": 6, "raw_value": 3},
)
# ADC_SMPRn.SMPx — 8 sample-time options.  Cycles are
# IP-specific (G0 has 1.5 / 3.5 / 7.5 / 12.5 / 19.5 / 39.5 / 79.5
# / 160.5).
_ADC_G0_SAMPLE_TIME_ROWS: tuple[dict[str, Any], ...] = (
    {"cycles": "1.5", "raw_value": 0},
    {"cycles": "3.5", "raw_value": 1},
    {"cycles": "7.5", "raw_value": 2},
    {"cycles": "12.5", "raw_value": 3},
    {"cycles": "19.5", "raw_value": 4},
    {"cycles": "39.5", "raw_value": 5},
    {"cycles": "79.5", "raw_value": 6},
    {"cycles": "160.5", "raw_value": 7},
)
# ADC_CFGR2.OVSR — oversampling ratio (G0 supports 2..256 ×).
_ADC_G0_OVERSAMPLING_ROWS: tuple[dict[str, Any], ...] = tuple(
    {"ratio": 2 ** (i + 1), "raw_value": i} for i in range(8)
)
# ADC_CFGR1.EXTSEL — 8 external triggers on G0.  The trigger
# names are TIM1_TRGO2 / TIM1_CC4 / TIM2_TRGO / TIM3_TRGO /
# TIM15_TRGO / TIM6_TRGO / EXTI11 (G0x1 with subset).
_ADC_G0_EXTERNAL_TRIGGER_ROWS: tuple[dict[str, Any], ...] = (
    {"trigger": "TIM1_TRGO2", "raw_value": 0},
    {"trigger": "TIM1_CC4", "raw_value": 1},
    {"trigger": "TIM2_TRGO", "raw_value": 2},
    {"trigger": "TIM3_TRGO", "raw_value": 3},
    {"trigger": "TIM15_TRGO", "raw_value": 4},
    {"trigger": "TIM6_TRGO", "raw_value": 5},
    {"trigger": "EXTI11", "raw_value": 7},
)

ADC_G0_V3_TIER = TierMapping(
    ip_name="ADC",
    ip_version_pattern=re.compile(r"^aditf4_v3_\d+_G0_Cube$"),
    projections=(
        TierProjection("adc_resolution_options", _ADC_G0_RESOLUTION_ROWS),
        TierProjection("adc_sample_time_options", _ADC_G0_SAMPLE_TIME_ROWS),
        TierProjection("adc_oversampling_options", _ADC_G0_OVERSAMPLING_ROWS),
        TierProjection("adc_external_triggers", _ADC_G0_EXTERNAL_TRIGGER_ROWS),
    ),
)

# STM32F4 ADC — `aditf2_v1_x_Cube` IP.  No oversampling;
# resolutions are 12/10/8/6 same as G0.  Sample-time encoding
# is different (3/15/28/56/84/112/144/480 cycles vs G0's
# 1.5..160.5).
_ADC_F4_RESOLUTION_ROWS = _ADC_G0_RESOLUTION_ROWS  # same encoding
_ADC_F4_SAMPLE_TIME_ROWS: tuple[dict[str, Any], ...] = (
    {"cycles": "3", "raw_value": 0},
    {"cycles": "15", "raw_value": 1},
    {"cycles": "28", "raw_value": 2},
    {"cycles": "56", "raw_value": 3},
    {"cycles": "84", "raw_value": 4},
    {"cycles": "112", "raw_value": 5},
    {"cycles": "144", "raw_value": 6},
    {"cycles": "480", "raw_value": 7},
)
# F4 EXTSEL is 4 bits (16 sources).  Common subset for F405 /
# F407 — RM0090 §13.13.4 table 38.  Other F4 chips share the
# core entries.
_ADC_F4_EXTERNAL_TRIGGER_ROWS: tuple[dict[str, Any], ...] = (
    {"trigger": "TIM1_CC1", "raw_value": 0},
    {"trigger": "TIM1_CC2", "raw_value": 1},
    {"trigger": "TIM1_CC3", "raw_value": 2},
    {"trigger": "TIM2_CC2", "raw_value": 3},
    {"trigger": "TIM2_CC3", "raw_value": 4},
    {"trigger": "TIM2_CC4", "raw_value": 5},
    {"trigger": "TIM2_TRGO", "raw_value": 6},
    {"trigger": "TIM3_CC1", "raw_value": 7},
    {"trigger": "TIM3_TRGO", "raw_value": 8},
    {"trigger": "TIM4_CC4", "raw_value": 9},
    {"trigger": "TIM5_CC1", "raw_value": 10},
    {"trigger": "TIM5_CC2", "raw_value": 11},
    {"trigger": "TIM5_CC3", "raw_value": 12},
    {"trigger": "TIM8_CC1", "raw_value": 13},
    {"trigger": "TIM8_TRGO", "raw_value": 14},
    {"trigger": "EXTI11", "raw_value": 15},
)

ADC_F4_V1_TIER = TierMapping(
    ip_name="ADC",
    ip_version_pattern=re.compile(r"^aditf2_v\d+_\d+_Cube$"),
    projections=(
        TierProjection("adc_resolution_options", _ADC_F4_RESOLUTION_ROWS),
        TierProjection("adc_sample_time_options", _ADC_F4_SAMPLE_TIME_ROWS),
        TierProjection("adc_external_triggers", _ADC_F4_EXTERNAL_TRIGGER_ROWS),
    ),
)


# ---------------------------------------------------------------------------
# Timer — STM32G0 / F4 advanced + general-purpose (gptimer2_v3_x)
# ---------------------------------------------------------------------------

# TIM_CR1.CMS — 4 alignment modes (edge + 3 center-aligned).
_TIM_ADV_ALIGNMENT_ROWS: tuple[dict[str, Any], ...] = (
    {"alignment": "edge", "raw_value": 0b00},
    {"alignment": "center-aligned-1", "raw_value": 0b01},
    {"alignment": "center-aligned-2", "raw_value": 0b10},
    {"alignment": "center-aligned-3", "raw_value": 0b11},
)
# TIM_CR2.MMS — 8 master-output modes.
_TIM_MASTER_OUTPUT_ROWS: tuple[dict[str, Any], ...] = (
    {"name": "Reset", "raw_value": 0b000},
    {"name": "Enable", "raw_value": 0b001},
    {"name": "Update", "raw_value": 0b010},
    {"name": "ComparePulse", "raw_value": 0b011},
    {"name": "OC1Ref", "raw_value": 0b100},
    {"name": "OC2Ref", "raw_value": 0b101},
    {"name": "OC3Ref", "raw_value": 0b110},
    {"name": "OC4Ref", "raw_value": 0b111},
)
# TIM_SMCR.TS — 8 trigger sources for slave-mode controller.
_TIM_TRIGGER_SOURCE_ROWS: tuple[dict[str, Any], ...] = (
    {"name": "ITR0", "raw_value": 0b000},
    {"name": "ITR1", "raw_value": 0b001},
    {"name": "ITR2", "raw_value": 0b010},
    {"name": "ITR3", "raw_value": 0b011},
    {"name": "TI1F_ED", "raw_value": 0b100},
    {"name": "TI1FP1", "raw_value": 0b101},
    {"name": "TI2FP2", "raw_value": 0b110},
    {"name": "ETRF", "raw_value": 0b111},
)
# Timer prescaler is 16-bit on every modern ST timer.  Render
# sparse representative options (powers of 2 + a few deltas) — a
# full 65,536-row table would bloat the YAML.
_TIM_PRESCALER_ROWS: tuple[dict[str, Any], ...] = tuple(
    {"prescaler_value": 2 ** i, "raw_value": 2 ** i - 1}
    for i in range(0, 17)  # 1 .. 65536
)
_TIM_MODE_FLAGS_ADV_ROWS: tuple[dict[str, Any], ...] = (
    {
        "supports_repetition_counter": True,
        "supports_dma_burst": True,
        "supports_xor_input": True,
        "supports_one_pulse_mode": True,
        "supports_encoder_mode": True,
    },
)
_TIM_MODE_FLAGS_GP_ROWS: tuple[dict[str, Any], ...] = (  # noqa: F841 -- kept for future per-instance gating
    {
        "supports_repetition_counter": False,
        "supports_dma_burst": True,
        "supports_xor_input": True,
        "supports_one_pulse_mode": True,
        "supports_encoder_mode": True,
    },
)
# PWM break-input rows for advanced timers (TIM1, TIM8, TIM15-17 on G0).
_PWM_BREAK_INPUT_ROWS: tuple[dict[str, Any], ...] = (
    {"input": "BKIN", "raw_value": 0},
    {"input": "BKIN2", "raw_value": 1},
)
# PWM dead-time options: DTG is 8 bits; the encoding is non-linear
# (4 ranges).  Render the 4 range boundaries — the codegen
# expands them at render-time.
_PWM_DEADTIME_ROWS: tuple[dict[str, Any], ...] = (
    {"range": "0..127×t_DTS", "raw_min": 0x00, "raw_max": 0x7F, "step_dts": 1},
    {"range": "64..126×t_DTS×2", "raw_min": 0x80, "raw_max": 0xBF, "step_dts": 2},
    {"range": "32..63×t_DTS×8", "raw_min": 0xC0, "raw_max": 0xDF, "step_dts": 8},
    {"range": "32..63×t_DTS×16", "raw_min": 0xE0, "raw_max": 0xFF, "step_dts": 16},
)
_PWM_MODE_FLAGS_ADV_ROWS: tuple[dict[str, Any], ...] = (
    {
        "supports_complementary_outputs": True,
        "supports_break_input": True,
        "supports_break_input_2": True,
        "supports_dead_time_insertion": True,
        "supports_combined_pwm": False,
        "supports_asymmetric_pwm": False,
    },
)

# CubeMX uses the same IP version (gptimer2_v3_x_Cube) for both
# advanced timers (TIM1) and general-purpose timers (TIM2/3/14/
# 15/16/17) on STM32G0; the *instance* tells you which subset of
# capabilities apply.  We emit the union (advanced superset)
# here — downstream consumers that need to gate on instance can
# look at the instance's register tree.
TIMER_GPTIMER_V3_TIER = TierMapping(
    ip_name="TIM1_8G0",
    ip_version_pattern=re.compile(r"^gptimer2_v3_\w+_Cube$"),
    projections=(
        TierProjection("timer_prescaler_options", _TIM_PRESCALER_ROWS),
        TierProjection("timer_trigger_sources", _TIM_TRIGGER_SOURCE_ROWS),
        TierProjection("timer_master_outputs", _TIM_MASTER_OUTPUT_ROWS),
        TierProjection("timer_mode_flags", _TIM_MODE_FLAGS_ADV_ROWS),
        TierProjection("pwm_alignment_options", _TIM_ADV_ALIGNMENT_ROWS),
        TierProjection("pwm_break_inputs", _PWM_BREAK_INPUT_ROWS),
        TierProjection("pwm_deadtime_options", _PWM_DEADTIME_ROWS),
        TierProjection("pwm_mode_flags", _PWM_MODE_FLAGS_ADV_ROWS),
    ),
)

# STM32F4 — TIM1 / TIM2 / TIM3 / etc. share the
# `gptimer2_v2_x_Cube` IP version.  TIM1 + TIM8 are advanced
# (have BDTR + RCR), the others are general-purpose; they share
# the same SVD-level fields (CR1.CMS, SMCR.TS, CR2.MMS, …).
# The mapping emits the SUPERSET (advanced); consumers needing
# per-instance gating use the chip's register tree.
TIMER_F4_GPTIMER_V2_TIER = TierMapping(
    ip_name="TIM1_8",
    ip_version_pattern=re.compile(r"^gptimer2_v2_\w+_Cube$"),
    projections=(
        TierProjection("timer_prescaler_options", _TIM_PRESCALER_ROWS),
        TierProjection("timer_trigger_sources", _TIM_TRIGGER_SOURCE_ROWS),
        TierProjection("timer_master_outputs", _TIM_MASTER_OUTPUT_ROWS),
        TierProjection("timer_mode_flags", _TIM_MODE_FLAGS_ADV_ROWS),
        TierProjection("pwm_alignment_options", _TIM_ADV_ALIGNMENT_ROWS),
        TierProjection("pwm_break_inputs", _PWM_BREAK_INPUT_ROWS),
        TierProjection("pwm_deadtime_options", _PWM_DEADTIME_ROWS),
        TierProjection("pwm_mode_flags", _PWM_MODE_FLAGS_ADV_ROWS),
    ),
)


# ---------------------------------------------------------------------------
# Registry — sequence of TierMapping rows the projector walks.
#
# When multiple rows match a peripheral's IP version, the FIRST
# match wins (sort by specificity from caller — most-specific
# patterns first).  When two peripherals on the same chip
# contribute the same target_field, the projector merges row
# sets with raw_value-level deduplication.
# ---------------------------------------------------------------------------


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
    """Look up the first TierMapping whose ``ip_version_pattern``
    matches ``ip_version``.  ``ip_name`` is currently unused —
    reserved for future disambiguation when two ip_versions
    collide on shape but split on name.
    """
    del ip_name
    for mapping in ALL_TIER_MAPPINGS:
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
