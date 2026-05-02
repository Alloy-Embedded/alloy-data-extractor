"""STM32 hand-curated overlay → v2.1 enrichment payload.

Reads ``data/vendors/st/<family>/family.toml`` (and optionally
``devices/<chip>.toml`` per-device overrides) and produces a v2.1
enrichment payload carrying the chip facts that no upstream source
publishes uniformly:

* ADC calibration ROM addresses + nominal voltages + cal temps
  (TS_CAL1, TS_CAL2, VREFINT_CAL — sourced from the family
  reference manual + CMSIS device header).
* ADC internal channel mapping (vrefint / temperature_sensor /
  vbat → channel index).
* I²C TIMINGR / CCR+TRISE precomputed presets per
  (speed × source-clock) pair (per AN4235).
* Named system-clock profiles (``post-reset``, ``pll-hsi16-64mhz``,
  ``pll-hse-72mhz``) with full PLL multiplier / divider tables.
* Memory regions (FLASH / SRAM base + size from the family RM).
* Per-IP `max_clock` overrides.

Marked ``provenance.primary = "stm32-overlay:<family>"`` so the
merge engine treats it as enrichment, never as authority for
register layout.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bytes_with_unit(value: int) -> str:
    """Render a byte count with the largest exact unit suffix."""
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if value % scale == 0 and value >= scale:
            return f"{value // scale}{unit}"
    return f"{value}B"


def _hz_with_unit(value: int) -> str:
    """Render a Hz value with kHz/MHz/GHz suffix when exact."""
    for unit, scale in (("GHz", 1_000_000_000), ("MHz", 1_000_000), ("kHz", 1_000)):
        if value % scale == 0 and value >= scale:
            return f"{value // scale}{unit}"
    return f"{value}Hz"


def _hex_addr(value: int) -> int | str:
    return f"0x{value:X}" if value >= 0x100 else value


def _shallow_merge(family: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    """Per-device TOML overrides win at the top level only.  Nested
    sections are replaced wholesale (we don't deep-merge ADC blocks
    yet — keeps the contract simple and predictable)."""
    out: dict[str, Any] = {**family}
    for k, v in device.items():
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Section converters
# ---------------------------------------------------------------------------


def _build_memory(toml: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in toml.get("memories") or []:
        if not isinstance(r, dict):
            continue
        size_bytes = r.get("size_bytes") or r.get("size")
        if not isinstance(size_bytes, int):
            continue
        # Don't use ``or`` — H7's ITCM at base_address=0x0 reads as
        # falsy and would silently disappear.
        base = r.get("base_address") if "base_address" in r else r.get("base")
        if not isinstance(base, int):
            continue
        access = r.get("access") or "rwx"
        out: dict[str, Any] = {
            "id":     str(r.get("name") or r.get("id") or "unknown").lower(),
            "base":   _hex_addr(base),
            "size":   _bytes_with_unit(size_bytes),
            "access": access,
        }
        # Map the legacy `address_space = "code" | "data"` to v2.1 alias.
        space = r.get("address_space")
        if space == "code":
            out["alias"] = "code"
        elif space == "data":
            out["alias"] = "data"
        if r.get("role"):
            out["role"] = r["role"]
        rows.append(out)
    return rows


def _build_clock(toml: dict[str, Any]) -> dict[str, Any] | None:
    sysclk = toml.get("system_clock")
    if not isinstance(sysclk, dict):
        return None

    profiles: list[dict[str, Any]] = []

    post_reset = sysclk.get("post_reset_profile")
    if isinstance(post_reset, dict):
        profile = {
            "id":            str(post_reset.get("name", "post-reset")),
            "kind":          "post-reset",
            "sysclk":        _hz_with_unit(int(post_reset["sysclk_hz"])),
            "sysclk_source": str(post_reset.get("source", "unknown")).lower(),
        }
        for key in ("hclk_hz", "pclk_hz", "pll_m", "pll_n", "pll_r"):
            if key in post_reset:
                profile[key] = post_reset[key]
        profiles.append(profile)

    for prof in sysclk.get("recommended_profiles") or []:
        if not isinstance(prof, dict):
            continue
        profile = {
            "id":            str(prof.get("name", "unknown")),
            "kind":          "recommended",
            "sysclk":        _hz_with_unit(int(prof["sysclk_hz"])),
            "sysclk_source": str(prof.get("source", "unknown")).lower(),
        }
        for key in ("hclk_hz", "pclk_hz", "pll_m", "pll_n", "pll_r", "pll_p", "pll_q"):
            if key in prof:
                profile[key] = prof[key]
        profiles.append(profile)

    if not profiles:
        return None

    # Synthesize a minimal oscillator + domain block — the real
    # clock-tree comes from CubeMX enrichment further upstream.
    return {
        "oscillators": {
            "hsi": {"freq": "16MHz", "kind": "rc-internal"},
            "hse": {"freq": "0Hz",   "kind": "crystal-external", "optional": True},
        },
        "domains":  [{"id": "sysclk", "sources": ["hsi", "hse"]}],
        "profiles": profiles,
    }


def _build_adc_calibration(toml: dict[str, Any]) -> dict[str, Any] | None:
    """Compose the ``peripherals[adc1].calibration`` block."""
    adc = toml.get("adc")
    if not isinstance(adc, dict):
        return None
    cal_block: dict[str, Any] = {}
    context = adc.get("calibration_context") or {}
    for point in adc.get("calibration_data_points") or []:
        kind = point.get("kind", "").lower()
        addr = point.get("address")
        if not isinstance(addr, int) or not kind:
            continue
        entry: dict[str, Any] = {
            "rom_addr":  _hex_addr(addr),
            "size_bits": point.get("size_bits", 16),
        }
        # Map the legacy ``kind`` strings onto v2.1's calibration
        # data-point names (vrefint / ts_cal_low / ts_cal_high).
        v21_key = {
            "vrefint_cal": "vrefint",
            "ts_cal_low":  "ts_cal_low",
            "ts_cal_high": "ts_cal_high",
        }.get(kind)
        if v21_key is None:
            continue
        if kind == "vrefint_cal":
            nominal_mv = point.get("semantic_constant") or context.get("vrefint_nominal_mv")
            if nominal_mv is not None:
                entry["nominal_mv"] = nominal_mv
        else:
            temp = point.get("semantic_constant")
            if temp is not None:
                entry["temp_celsius"] = temp
            cal_v = context.get("cal_voltage_mv")
            if cal_v is not None:
                entry["vdda_calibration"] = cal_v
        cal_block[v21_key] = entry
    return cal_block or None


def _build_adc_channels(toml: dict[str, Any]) -> dict[str, str] | None:
    """Compose ``peripherals[adc1].channels`` (channel_index → role)."""
    adc = toml.get("adc")
    if not isinstance(adc, dict):
        return None
    out: dict[str, str] = {}
    for channel in adc.get("internal_channels") or []:
        idx = channel.get("channel_index")
        kind = channel.get("kind")
        if isinstance(idx, int) and isinstance(kind, str):
            out[f"ch{idx}"] = kind
    return out or None


def _build_i2c_timing_presets(toml: dict[str, Any]) -> list[dict[str, Any]]:
    """Compose I²C ``timing_presets[]`` from any TOML
    ``[[i2c.timing_presets]]`` rows.  Family TOML usually carries
    only the speed_options list (no precomputed timings) — those
    rows ship in per-device overrides where the source-clock is
    known.
    """
    i2c = toml.get("i2c")
    if not isinstance(i2c, dict):
        return []
    rows: list[dict[str, Any]] = []
    for preset in i2c.get("timing_presets") or []:
        if not isinstance(preset, dict):
            continue
        speed = preset.get("speed_hz")
        source = preset.get("source_clock_hz")
        if not isinstance(speed, int) or not isinstance(source, int):
            continue
        row: dict[str, Any] = {
            "speed":        _hz_with_unit(speed),
            "source_clock": _hz_with_unit(source),
        }
        for key in ("timingr_value", "ccr", "trise"):
            if key in preset and isinstance(preset[key], int):
                v21_key = "timingr" if key == "timingr_value" else key
                row[v21_key] = _hex_addr(preset[key])
        rows.append(row)
    return rows


def _adc_max_clock(toml: dict[str, Any]) -> str | None:
    adc = toml.get("adc") or {}
    val = adc.get("max_clock_hz")
    return _hz_with_unit(val) if isinstance(val, int) else None


def _i2c_max_clock(toml: dict[str, Any]) -> str | None:
    i2c = toml.get("i2c") or {}
    val = i2c.get("max_clock_hz")
    return _hz_with_unit(val) if isinstance(val, int) else None


def _uart_max_baud(toml: dict[str, Any]) -> int | None:
    uart = toml.get("uart") or {}
    val = uart.get("max_baud_hz")
    return val if isinstance(val, int) else None


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    overlay_root: Path,
) -> dict[str, Any]:
    """Read ``data/vendors/<vendor>/<family>/family.toml`` (+ optional
    ``devices/<device>.toml`` override) and emit a v2.1 enrichment
    payload."""
    family_toml = overlay_root / "vendors" / vendor / family / "family.toml"
    device_toml = overlay_root / "vendors" / vendor / family / "devices" / f"{device}.toml"

    if not family_toml.is_file():
        raise FileNotFoundError(f"Family overlay not found: {family_toml}")
    family_data = tomllib.loads(family_toml.read_text(encoding="utf-8"))
    device_data: dict[str, Any] = {}
    if device_toml.is_file():
        device_data = tomllib.loads(device_toml.read_text(encoding="utf-8"))
    composed = _shallow_merge(family_data, device_data)

    # Build the per-peripheral enrichment.  The SVD's ADC peripheral
    # is named ``ADC`` on small chips (STM32G030) and ``ADC1`` on
    # larger ones (STM32G0B1, F4 family).  Emit BOTH ids — the merge
    # engine drops the phantom (no-match) row, and the surviving
    # row matches whichever the primary actually declared.
    adc_peripherals: list[dict[str, Any]] = []
    cal = _build_adc_calibration(composed)
    chans = _build_adc_channels(composed)
    if cal or chans:
        max_clock = _adc_max_clock(composed)
        for adc_id in ("adc", "adc1"):
            row: dict[str, Any] = {"id": adc_id, "template": "adc"}
            if max_clock:
                row["max_clock_override"] = max_clock
            if cal:
                row["calibration"] = cal
            if chans:
                row["channels"] = chans
            adc_peripherals.append(row)

    # Compose I²C peripherals (only when timing presets supplied —
    # otherwise the merge engine has nothing to add per-instance).
    i2c_peripherals: list[dict[str, Any]] = []
    timing_presets = _build_i2c_timing_presets(composed)
    if timing_presets:
        for i2c_id in ("i2c", "i2c1", "i2c2"):
            i2c_peripherals.append({
                "id": i2c_id, "template": "i2c",
                "timing_presets": timing_presets,
            })

    # Compose templates with `max_clock` / `max_baud` overrides.
    templates: dict[str, dict[str, Any]] = {}
    if (mc := _adc_max_clock(composed)):
        templates.setdefault("adc", {})["max_clock"] = mc
    if (mc := _i2c_max_clock(composed)):
        templates.setdefault("i2c", {})["max_clock"] = mc
    if (mb := _uart_max_baud(composed)):
        templates.setdefault("usart", {})["max_baud"] = mb

    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": vendor, "family": family, "device": device,
            "core":   {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
        },
        "provenance": {
            "primary":  f"stm32-overlay:{family}",
            "authored": "hand",
            "notes":    "Hand-curated family overlay (RM + datasheet + CMSIS header).",
        },
        "memory":      _build_memory(composed) or [
            {"id": "flash", "base": "0x00000000", "size": "1B",
             "access": "rx", "role": "extractor-placeholder"},
        ],
    }

    clock_block = _build_clock(composed)
    if clock_block:
        payload["clock"] = clock_block
    else:
        payload["clock"] = {
            "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
            "domains":     [{"id": "sysclk", "sources": ["unknown"]}],
        }

    if templates:
        payload["templates"] = templates
    payload["peripherals"] = adc_peripherals + i2c_peripherals
    payload["pinout"] = [{"signal": "RESET"}]
    return payload


__all__ = ["extract_device"]
