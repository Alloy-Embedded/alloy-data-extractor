"""Microchip hand-curated overlay → v2.1 enrichment payload.

Mirror of ``stm32_overlay_v2_1`` for Microchip families (AVR-DA,
AVR-DB, AVR-DD, AVR-EA, ATmega, ATtiny, SAM-D/E/G, …).

Reads ``data/vendors/microchip/<family>/family.toml`` (+ optional
per-device override at ``devices/<chip>.toml``) and emits a v2.1
enrichment payload carrying the chip facts no upstream source
publishes uniformly:

* Memory regions (flash + sram + harvard space tagging).
* Named system-clock profiles with full source/divider tables.
* ``templates.<ip>.max_clock`` / ``max_baud`` per-IP ceilings
  from the family reference manual.

Marked ``provenance.primary = "microchip-overlay:<family>"`` so
the merge engine treats it as enrichment, never as authority for
register layout (the ATDF already owns that).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers — share unit-suffix logic with the STM32 overlay.
# ---------------------------------------------------------------------------


def _bytes_with_unit(value: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if value % scale == 0 and value >= scale:
            return f"{value // scale}{unit}"
    return f"{value}B"


def _hz_with_unit(value: int) -> str:
    for unit, scale in (("GHz", 1_000_000_000), ("MHz", 1_000_000), ("kHz", 1_000)):
        if value % scale == 0 and value >= scale:
            return f"{value // scale}{unit}"
    return f"{value}Hz"


def _hex_addr(value: int) -> int | str:
    return f"0x{value:X}" if value >= 0x100 else value


def _shallow_merge(family: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {**family}
    for k, v in device.items():
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Section converters
# ---------------------------------------------------------------------------


def _build_memory(toml: dict[str, Any]) -> list[dict[str, Any]]:
    """Project family-overlay memories[] into v2.1 memory rows.

    AVR Harvard: ``address_space = code`` → v2.1 alias=code (Flash);
    ``address_space = data`` → v2.1 alias=data (SRAM).  We also stamp
    the v2.1 ``address_space`` enum tag (``program`` / ``data``)
    so codegen can pick the right linker section.
    """
    rows: list[dict[str, Any]] = []
    for r in toml.get("memories") or []:
        if not isinstance(r, dict):
            continue
        size_bytes = r.get("size_bytes") if "size_bytes" in r else r.get("size")
        if not isinstance(size_bytes, int):
            continue
        # Don't use ``or`` here — ``base_address = 0`` (AVR Flash)
        # is a valid value that ``or`` short-circuits as falsy.
        base = r.get("base_address") if "base_address" in r else r.get("base")
        if not isinstance(base, int):
            continue
        out: dict[str, Any] = {
            "id":     str(r.get("name") or r.get("id") or "unknown").lower(),
            "base":   _hex_addr(base),
            "size":   _bytes_with_unit(size_bytes),
            "access": r.get("access") or "rwx",
        }
        # `address_space` in the TOML is the legacy v1 alias model
        # (``code`` / ``data``); v2.1 splits this into:
        #   * ``alias``         — code|data|…
        #   * ``address_space`` — closed enum (program/data/eeprom/
        #                                       fuse/signature)
        legacy_space = r.get("address_space")
        if legacy_space == "code":
            out["alias"] = "code"
            out["address_space"] = "program"
        elif legacy_space == "data":
            out["alias"] = "data"
            out["address_space"] = "data"
        if r.get("role"):
            out["role"] = r["role"]
        rows.append(out)
    return rows


def _build_clock(toml: dict[str, Any]) -> dict[str, Any] | None:
    """Project ``[system_clock]`` block into v2.1 ``clock``."""
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
        for key in ("hclk_hz", "pclk_hz"):
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
        for key in ("hclk_hz", "pclk_hz"):
            if key in prof:
                profile[key] = prof[key]
        profiles.append(profile)

    if not profiles:
        return None

    # AVR-DA's oscillators (OSCHF, OSC32K, EXTCLK) — synthesised here
    # since ATDF doesn't carry them as separate clock sources.
    return {
        "oscillators": {
            "oschf":  {"freq": "24MHz", "kind": "rc-internal"},
            "osc32k": {"freq": "32kHz", "kind": "rc-internal"},
            "extclk": {"freq": "0Hz",   "kind": "crystal-external", "optional": True},
        },
        "domains": [{"id": "clk_per",
                      "sources": ["oschf", "osc32k", "extclk"]}],
        "profiles": profiles,
    }


def _adc_max_clock(toml: dict[str, Any]) -> str | None:
    val = (toml.get("adc") or {}).get("max_clock_hz")
    return _hz_with_unit(val) if isinstance(val, int) else None


def _spi_max_clock(toml: dict[str, Any]) -> str | None:
    val = (toml.get("spi") or {}).get("max_clock_hz")
    return _hz_with_unit(val) if isinstance(val, int) else None


def _i2c_max_clock(toml: dict[str, Any]) -> str | None:
    val = (toml.get("i2c") or {}).get("max_clock_hz")
    return _hz_with_unit(val) if isinstance(val, int) else None


def _uart_max_baud(toml: dict[str, Any]) -> int | None:
    val = (toml.get("uart") or {}).get("max_baud_hz")
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
    per-device override) and emit a v2.1 enrichment payload."""
    family_toml = overlay_root / "vendors" / vendor / family / "family.toml"
    device_toml = overlay_root / "vendors" / vendor / family / "devices" / f"{device}.toml"

    if not family_toml.is_file():
        raise FileNotFoundError(f"Family overlay not found: {family_toml}")
    family_data = tomllib.loads(family_toml.read_text(encoding="utf-8"))
    device_data: dict[str, Any] = {}
    if device_toml.is_file():
        device_data = tomllib.loads(device_toml.read_text(encoding="utf-8"))
    composed = _shallow_merge(family_data, device_data)

    # Compose templates with `max_clock` / `max_baud` ceilings.
    templates: dict[str, dict[str, Any]] = {}
    if (mc := _adc_max_clock(composed)):
        templates.setdefault("adc", {})["max_clock"] = mc
    if (mc := _spi_max_clock(composed)):
        templates.setdefault("spi", {})["max_clock"] = mc
    if (mc := _i2c_max_clock(composed)):
        templates.setdefault("twi", {})["max_clock"] = mc
        templates.setdefault("i2c", {})["max_clock"] = mc
    if (mb := _uart_max_baud(composed)):
        templates.setdefault("usart", {})["max_baud"] = mb

    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": vendor, "family": family, "device": device,
            "core":   {"isa": "avr", "name": "avr-avr", "bits": 8},
        },
        "provenance": {
            "primary":  f"microchip-overlay:{family}",
            "authored": "hand",
            "notes":    "Hand-curated family overlay (datasheet + RM + ATDF).",
        },
        "memory": _build_memory(composed) or [
            {"id": "flash", "base": "0x00000000", "size": "1B",
             "access": "rx", "role": "extractor-placeholder"},
        ],
    }

    clock_block = _build_clock(composed)
    payload["clock"] = clock_block or {
        "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
        "domains":     [{"id": "sysclk", "sources": ["unknown"]}],
    }

    if templates:
        payload["templates"] = templates
    payload["peripherals"] = []
    payload["pinout"]      = [{"signal": "RESET"}]
    return payload


__all__ = ["extract_device"]
