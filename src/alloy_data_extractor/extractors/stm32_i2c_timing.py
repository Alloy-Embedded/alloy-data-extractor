"""STM32 I2C TIMINGR preset computation —
`complete-stm32-tier-coverage` Phase 6.

Pure helper.  Given a target I2C bus speed (100k / 400k / 1M)
and a source-clock frequency (the I2C kernel clock — typically
SYSCLK or HSI16), computes the
``(presc, scldel, sdadel, sclh, scll)`` tuple that programs the
STM32 I2C TIMINGR register to hit those parameters within the
I2C-bus standard's tHD;DAT / tSU;DAT requirements.

This is the formula ST publishes in AN4235 §3.1.2 ("I2C timing
configuration tool") — the canonical reference for I2C timing
on STM32 F0 / F3 / F7 / G0 / L0 / L4 / U5.  The formula is the
same on every chip; only the available source clock changes.

Usage::

    from alloy_data_extractor.extractors.stm32_i2c_timing import (
        compute_i2c_timing_preset,
    )

    preset = compute_i2c_timing_preset(
        speed_hz=100_000,
        source_clock_hz=64_000_000,
    )
    # preset is an I2cTimingPreset dataclass
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class I2cTimingPreset:
    """Computed values for one STM32 I2C TIMINGR register."""

    speed_hz: int
    source_clock_hz: int
    presc: int  # PRESC field — 4 bits
    sdadel: int  # SDADEL field — 4 bits (data hold time)
    scldel: int  # SCLDEL field — 4 bits (data setup time)
    sclh: int  # SCLH field — 8 bits (SCL high period)
    scll: int  # SCLL field — 8 bits (SCL low period)

    @property
    def timingr_value(self) -> int:
        """Pack the fields into the canonical TIMINGR layout
        (PRESC[31:28] | SCLDEL[23:20] | SDADEL[19:16] |
        SCLH[15:8] | SCLL[7:0]).
        """
        return (
            (self.presc & 0xF) << 28
            | (self.scldel & 0xF) << 20
            | (self.sdadel & 0xF) << 16
            | (self.sclh & 0xFF) << 8
            | (self.scll & 0xFF)
        )


# Per-bus-speed timing requirements from the I²C-bus specification
# (UM10204 rev. 7.0).  Times in nanoseconds.
#
# tHD_DAT_min: minimum data hold time after SCL falling edge.
# tSU_DAT_min: minimum data setup time before SCL rising edge.
# tLOW_min:    minimum SCL low period.
# tHIGH_min:   minimum SCL high period.
_BUS_REQUIREMENTS: dict[int, dict[str, float]] = {
    100_000: {
        "tHD_DAT_min": 5_000.0,  # actually 0; ST uses 5µs guard
        "tSU_DAT_min": 250.0,
        "tLOW_min": 4_700.0,
        "tHIGH_min": 4_000.0,
    },
    400_000: {
        "tHD_DAT_min": 0.0,
        "tSU_DAT_min": 100.0,
        "tLOW_min": 1_300.0,
        "tHIGH_min": 600.0,
    },
    1_000_000: {
        "tHD_DAT_min": 0.0,
        "tSU_DAT_min": 50.0,
        "tLOW_min": 500.0,
        "tHIGH_min": 260.0,
    },
}


def compute_i2c_timing_preset(
    *,
    speed_hz: int,
    source_clock_hz: int,
) -> I2cTimingPreset:
    """Compute the TIMINGR preset for one (speed, source_clock) pair.

    Algorithm (from ST AN4235 §3.1.2):

    1.  Pick PRESC such that ``t_PRESC = (PRESC + 1) / source_clock``
        is between 100 ns and 1 µs (PRESC ranges 0..15).
    2.  Compute SCLL / SCLH from the bus-speed period and PRESC,
        ensuring tLOW_min and tHIGH_min are met.
    3.  Pick SCLDEL ≥ tSU;DAT_min / t_PRESC and SDADEL covering
        tHD;DAT_min within the analog filter delay budget.

    Determinism: same inputs → byte-identical preset.
    """
    if speed_hz not in _BUS_REQUIREMENTS:
        raise ValueError(
            f"compute_i2c_timing_preset: unsupported speed {speed_hz} Hz; "
            f"supported: {sorted(_BUS_REQUIREMENTS)}"
        )
    if source_clock_hz <= 0:
        raise ValueError(
            f"compute_i2c_timing_preset: source_clock_hz must be > 0, "
            f"got {source_clock_hz}"
        )
    bus = _BUS_REQUIREMENTS[speed_hz]
    src_period_ns = 1_000_000_000.0 / source_clock_hz
    bus_period_ns = 1_000_000_000.0 / speed_hz

    # Step 1: pick PRESC.  Target a ~125ns t_PRESC for standard /
    # fast bus speeds (the canonical AN4235 default); for fast-plus
    # (1 MHz) shrink to ~62.5ns.
    target_presc_period_ns = 62.5 if speed_hz >= 1_000_000 else 125.0
    presc = max(0, round(target_presc_period_ns / src_period_ns) - 1)
    presc = min(presc, 15)
    presc_period_ns = (presc + 1) * src_period_ns

    # Step 2: SCLL / SCLH from bus period.  AN4235 splits 50/50
    # for standard mode (symmetric); for fast / fast-plus the
    # spec mandates tLOW > tHIGH so 60/40 split.
    if speed_hz <= 100_000:
        low_period_ns = bus_period_ns * 0.5
        high_period_ns = bus_period_ns * 0.5
    else:
        low_period_ns = max(bus_period_ns * 0.6, bus["tLOW_min"])
        high_period_ns = max(bus_period_ns * 0.4, bus["tHIGH_min"])

    scll = max(0, round(low_period_ns / presc_period_ns) - 1)
    sclh = max(0, round(high_period_ns / presc_period_ns) - 1)
    scll = min(scll, 0xFF)
    sclh = min(sclh, 0xFF)

    # Step 3: SCLDEL covers tSU;DAT_min.
    scldel = max(1, round(bus["tSU_DAT_min"] / presc_period_ns))
    scldel = min(scldel, 0xF)

    # SDADEL covers tHD;DAT_min minus the analog/digital filter
    # delay.  We allocate at most 4 PRESC ticks (AN4235 default).
    sdadel = min(4, round(bus["tHD_DAT_min"] / presc_period_ns))
    sdadel = max(0, sdadel)
    sdadel = min(sdadel, 0xF)

    return I2cTimingPreset(
        speed_hz=speed_hz,
        source_clock_hz=source_clock_hz,
        presc=presc,
        sdadel=sdadel,
        scldel=scldel,
        sclh=sclh,
        scll=scll,
    )


def compute_i2c_timing_presets_for_speeds_and_clocks(
    *,
    speeds_hz: list[int],
    source_clocks_hz: list[int],
) -> list[I2cTimingPreset]:
    """Compute the cross-product of presets for the given speeds
    and source clocks.  Useful for projecting a chip's
    `i2c_timing_presets[]` array from `i2c.speed_options` ×
    `system_clock_profiles[*].sysclk_hz`.

    Output is sorted by ``(speed_hz, source_clock_hz)`` for
    byte-stable rendering.
    """
    presets: list[I2cTimingPreset] = []
    for speed in speeds_hz:
        for source_clock in source_clocks_hz:
            presets.append(
                compute_i2c_timing_preset(
                    speed_hz=speed, source_clock_hz=source_clock
                )
            )
    presets.sort(key=lambda p: (p.speed_hz, p.source_clock_hz))
    return presets


__all__ = [
    "I2cTimingPreset",
    "compute_i2c_timing_preset",
    "compute_i2c_timing_presets_for_speeds_and_clocks",
]
