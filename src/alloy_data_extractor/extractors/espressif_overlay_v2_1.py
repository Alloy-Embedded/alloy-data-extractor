"""Espressif hand-curated overlay → v2.1 enrichment payload.

Mirror of ``microchip_overlay_v2_1`` for the ESP32 family
(esp32, esp32s2, esp32s3, esp32c2, esp32c3, esp32c6, esp32h2,
esp32p4).

Reads ``data/vendors/espressif/<family>/family.toml`` (+ optional
per-device override) and emits the v2.1 enrichment that no
upstream source ships uniformly:

* Memory regions (DROM / DRAM / IROM / IRAM / RTC slow + fast /
  external Flash + PSRAM XIP windows).
* Named system-clock profiles with full source chain
  (RC_FAST / XTAL / PLL_CPU at 80/160/240 MHz / etc.).
* Optional ``wireless`` / ``power_domains`` / ``strapping_pins``
  blocks (Frente C of the ESP32 enrichment plan).
* ``templates.<ip>.max_clock`` / ``max_baud`` per-IP ceilings
  from the chip TRM.

Marked ``provenance.primary = "espressif-overlay:<family>"`` so
the merge engine treats it as enrichment, never as authority for
register layout (the CMSIS-SVD already owns that).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
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

    ESP32 doesn't model Harvard at the user-visible address space
    (the bus matrix presents both code and data through one
    32-bit address), so we don't tag ``alias`` / ``address_space``
    unless the TOML explicitly asks for it.
    """
    rows: list[dict[str, Any]] = []
    for r in toml.get("memories") or []:
        if not isinstance(r, dict):
            continue
        size_bytes = r.get("size_bytes") if "size_bytes" in r else r.get("size")
        if not isinstance(size_bytes, int):
            continue
        # `base_address = 0` is a valid value (ITCM-style), so use
        # `in` rather than truthy check.
        base = r.get("base_address") if "base_address" in r else r.get("base")
        if not isinstance(base, int):
            continue
        out: dict[str, Any] = {
            "id":     str(r.get("name") or r.get("id") or "unknown").lower(),
            "base":   _hex_addr(base),
            "size":   _bytes_with_unit(size_bytes),
            "access": r.get("access") or "rwx",
        }
        if r.get("role"):
            out["role"] = r["role"]
        if r.get("address_space"):
            out["address_space"] = r["address_space"]
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

    # Oscillators from TOML (ESP32-specific: rc_fast, xtal, xtal32k,
    # rc_slow, pll_cpu, pll_periph, …).  Falls back to the well-known
    # ESP32 set when the TOML doesn't enumerate.
    oscillators_toml = sysclk.get("oscillators") or {}
    oscillators: dict[str, Any] = {}
    for osc_id, osc_def in oscillators_toml.items():
        if not isinstance(osc_def, dict):
            continue
        entry: dict[str, Any] = {}
        if "freq_hz" in osc_def and isinstance(osc_def["freq_hz"], int):
            entry["freq"] = _hz_with_unit(osc_def["freq_hz"])
        elif "freq" in osc_def:
            entry["freq"] = osc_def["freq"]
        if "kind" in osc_def:
            entry["kind"] = osc_def["kind"]
        if osc_def.get("optional"):
            entry["optional"] = True
        oscillators[osc_id.lower()] = entry

    if not oscillators:
        # Fallback — pre-ESP-IDF integration assumes a 40 MHz crystal,
        # 17.5 MHz internal RC fast, and 150 kHz RC slow (standard
        # ESP32-classic tap-out).  Override per-family in TOML.
        oscillators = {
            "xtal":    {"freq": "40MHz", "kind": "crystal-external"},
            "rc_fast": {"freq": "17.5MHz", "kind": "rc-internal"},
            "rc_slow": {"freq": "150kHz", "kind": "rc-internal"},
        }

    domains_toml = sysclk.get("domains") or []
    if domains_toml:
        domains = []
        for d in domains_toml:
            if not isinstance(d, dict):
                continue
            row: dict[str, Any] = {
                "id":      d.get("id", "unknown"),
                "sources": list(d.get("sources") or []),
            }
            domains.append(row)
    else:
        domains = [{
            "id":      "sysclk",
            "sources": list(oscillators.keys()),
        }]

    if not profiles:
        return {"oscillators": oscillators, "domains": domains}

    return {
        "oscillators": oscillators,
        "domains":     domains,
        "profiles":    profiles,
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
# Frente C extras
# ---------------------------------------------------------------------------


def _build_wireless(toml: dict[str, Any]) -> dict[str, Any] | None:
    """Project ``[wireless]`` block.  Schema additionalProperties:true
    at the top level lets us emit this without extending the schema."""
    w = toml.get("wireless")
    if not isinstance(w, dict) or not w:
        return None
    out: dict[str, Any] = {}
    if "wifi" in w:
        out["wifi"] = w["wifi"]
    if "bluetooth" in w:
        out["bluetooth"] = w["bluetooth"]
    if "ieee_802_15_4" in w:
        out["ieee_802_15_4"] = w["ieee_802_15_4"]
    if "thread" in w:
        out["thread"] = w["thread"]
    if "zigbee" in w:
        out["zigbee"] = w["zigbee"]
    return out or None


def _build_power_domains(toml: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw = toml.get("power_domains")
    if not isinstance(raw, list) or not raw:
        return None
    rows: list[dict[str, Any]] = []
    for d in raw:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        row: dict[str, Any] = {"id": str(d["id"]).lower()}
        if "description" in d:
            row["description"] = d["description"]
        if "peripherals" in d and isinstance(d["peripherals"], list):
            row["peripherals"] = [str(p).lower() for p in d["peripherals"]]
        if "sleep_modes" in d and isinstance(d["sleep_modes"], list):
            row["sleep_modes"] = list(d["sleep_modes"])
        rows.append(row)
    return rows or None


def _augment_strapping(
    pinout: list[dict[str, Any]] | None,
    toml: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Stamp ``boot_strap = true`` on pinout rows whose ``signal``
    matches an entry in ``[strapping_pins]``."""
    raw = toml.get("strapping_pins")
    if not isinstance(raw, list) or not raw:
        return pinout
    targets = {str(p).upper() for p in raw}
    if not pinout:
        # Synthesise stub pinout when none — the schema requires
        # ≥1 pin, and we surface the strapping signals so codegen
        # can still emit a strapping report.
        return [
            {"signal": p, "constraints": ["boot-strap"]}
            for p in sorted(targets)
        ]
    out: list[dict[str, Any]] = []
    for row in pinout:
        new_row = dict(row)
        sig = str(new_row.get("signal", "")).upper()
        if sig in targets:
            constraints = list(new_row.get("constraints") or [])
            if "boot-strap" not in constraints:
                constraints.append("boot-strap")
            new_row["constraints"] = constraints
        out.append(new_row)
    return out


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

    templates: dict[str, dict[str, Any]] = {}
    if (mc := _adc_max_clock(composed)):
        templates.setdefault("adc", {})["max_clock"] = mc
    if (mc := _spi_max_clock(composed)):
        templates.setdefault("spi", {})["max_clock"] = mc
    if (mc := _i2c_max_clock(composed)):
        templates.setdefault("i2c", {})["max_clock"] = mc
    if (mb := _uart_max_baud(composed)):
        templates.setdefault("uart", {})["max_baud"] = mb

    # Identity overrides — TOML can ship a per-device package +
    # description (e.g. "esp32-wroom32" module variant).
    identity_overrides: dict[str, Any] = {}
    if "package" in composed:
        identity_overrides["package"] = composed["package"]
    if "description" in composed:
        identity_overrides["description"] = composed["description"]

    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": vendor, "family": family, "device": device,
            **identity_overrides,
            # Espressif overlay never owns core authority — the SVD
            # primary already nailed it (xtensa-lx6, rv32imc, …).
            # We still need *something* so the standalone payload
            # validates; the merge engine prefers cmsis-svd.
            "core":   {"isa": "unknown", "name": "overlay-stub", "bits": 32},
        },
        "provenance": {
            "primary":  f"espressif-overlay:{family}",
            "authored": "hand",
            "notes":    "Hand-curated family overlay (TRM + ESP-IDF).",
        },
        "memory": _build_memory(composed) or [
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

    payload["peripherals"] = []

    # Pinout — start from TOML if provided (same shape as v2.1
    # pinout[]); apply strapping-pin augmentation regardless.
    pinout_raw = composed.get("pinout")
    pinout = pinout_raw if isinstance(pinout_raw, list) else None
    pinout = _augment_strapping(pinout, composed)
    payload["pinout"] = pinout or [{"signal": "RESET"}]

    # Frente C — wireless + power_domains as additionalProperties
    # on the root payload (schema is open at the top level).
    wireless = _build_wireless(composed)
    if wireless:
        payload["wireless"] = wireless
    power_domains = _build_power_domains(composed)
    if power_domains:
        payload["power_domains"] = power_domains

    return payload


__all__ = ["extract_device"]
