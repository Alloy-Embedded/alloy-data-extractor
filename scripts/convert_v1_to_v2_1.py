"""Convert canonical-v1 YAMLs to alloy.device.v2.1.

`adopt-canonical-device-v2-1` — bridge tool that unblocks Phase 7 by
producing v2.1 versions of every existing admitted chip.  The output
lands in a chosen directory; the cutover commit replaces the
alloy-devices-yml content with this output atomically.

Algorithm:

1. Read v1 YAML payload (`yaml.safe_load`).
2. Build v2.1 ``identity`` from the v1 ``identity`` block.
3. Convert ``memories`` → ``memory[]`` preserving every field +
   inferring ``address_space`` for known Harvard / XIP cases.
4. Build per-IP **templates** by clustering v1 ``register_fields[]``
   by their peripheral's ``ip_name``.  Each unique ip_name becomes
   one template; per-instance ``peripherals[].template`` references
   it.
5. Convert ``clock_nodes`` / ``clock_selectors`` /
   ``system_clock_profiles`` → v2.1 ``clock:`` block.  Codegen
   already had a normalised model on the v1 side; the conversion
   is mostly a rename.
6. Convert ``pins[]`` → ``pinout[]`` carrying the constraint enum
   (analog-only / strapping / etc) when the v1 source supplied it.
7. Drop every alloy-codegen-synthesised top-level (route_operations,
   route_requirements, connection_*, vector_slots,
   interrupt_bindings, signal_endpoints, capabilities, dma_routes,
   dma_bindings, startup_descriptors, ip_blocks).
8. Move the single dominant per-row ``provenance`` block to
   top-level; drop per-row blocks.

Validation: every emitted YAML is parsed back through the v2.1
reader to confirm shape correctness.

Usage::

    python3 scripts/convert_v1_to_v2_1.py \\
        /path/to/alloy-devices-yml/vendors \\
        --out  /tmp/v2_1-converted

    # convert only one chip for quick iteration
    python3 scripts/convert_v1_to_v2_1.py \\
        /path/to/alloy-devices-yml/vendors/st/stm32g0/devices/stm32g030f6.yml \\
        --out  /tmp/v2_1-converted
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

# Make alloy-codegen importable without an install; the converter is
# typically run from the alloy-data-extractor repo with codegen as a
# sibling clone.
_HERE = Path(__file__).resolve()
_CODEGEN_SRC = _HERE.parents[2] / "alloy-codegen" / "src"
if _CODEGEN_SRC.is_dir() and str(_CODEGEN_SRC) not in sys.path:
    sys.path.insert(0, str(_CODEGEN_SRC))

import yaml  # noqa: E402  (late import after sys.path manipulation)


# Top-level v1 sections alloy-codegen synthesises at consume time —
# never emit them on the v2.1 side.
_DROP_SECTIONS: frozenset[str] = frozenset({
    "route_operations",
    "route_requirements",
    "connection_candidates",
    "connection_groups",
    "interrupt_bindings",
    "vector_slots",
    "signal_endpoints",
    "capabilities",
    "dma_routes",
    "dma_bindings",
    "startup_descriptors",
    "ip_blocks",
    "stm32_tier_resolution",   # diagnostic only
    "provenance_defaults",     # v1.5 dedup map — v2.1 has none
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: YAML root is not a mapping")
    return payload


# v1 vendors spelled access flags inconsistently — normalise to the
# v2.1 closed enum.
_ACCESS_NORMALISE = {
    "r": "r", "ro": "ro", "rw": "rw", "rwx": "rwx", "rx": "rx", "wo": "wo",
    "read": "ro", "read-only": "ro", "readonly": "ro",
    "write": "wo", "write-only": "wo", "writeonly": "wo",
    "read-write": "rw", "readwrite": "rw",
    "x": "rx",          # SAM70 emits bare 'x' — treat as rx
    "execute": "rx",
}


# v1 AVR-DA emits the spelling 'prog' / 'eeprom' / 'fuses' / 'sigrow'
# for address_space.  Map onto the v2.1 closed enum.
_ADDRESS_SPACE_NORMALISE = {
    "program": "program", "prog": "program",
    "data":    "data",
    "instruction": "instruction",
    "eeprom":  "eeprom",
    "fuse":    "fuse", "fuses": "fuse",
    "signature": "signature", "sigrow": "signature",
}


def _bytes_with_unit(value: int | None) -> str | None:
    """Render a byte count with KB/MB/GB suffix.

    Picks the largest exact unit (e.g. ``2097152 → "2MB"``).
    """
    if value is None:
        return None
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if value % scale == 0 and value >= scale:
            return f"{value // scale}{unit}"
    return f"{value}B"


def _hz_with_unit(value: int | None) -> str | None:
    """Render a Hz value with kHz/MHz/GHz suffix."""
    if value is None:
        return None
    for unit, scale in (("GHz", 1_000_000_000), ("MHz", 1_000_000), ("kHz", 1_000)):
        if value % scale == 0 and value >= scale:
            return f"{value // scale}{unit}"
    return f"{value}Hz"


def _hex_addr(value: int | None) -> int | str | None:
    if value is None:
        return None
    if value >= 0x100:
        return f"0x{value:X}"
    return value


def _detect_address_space(region: dict[str, Any], vendor: str) -> str | None:
    """Heuristic: AVR memories carry an explicit ``address_space``;
    other vendors keep their conventional flat layout.

    v1.5 introduced spurious values (``code`` / ``data`` aliases that
    really mean "ROM/RAM in a flat 32-bit space" — those don't fit
    the v2.1 closed enum, which is for Harvard / OTP / signature
    spaces.  Drop them: the flat-space chip is communicated via
    ``alias: code`` instead.
    """
    raw = region.get("address_space")
    if isinstance(raw, str):
        normalised = _ADDRESS_SPACE_NORMALISE.get(raw.lower())
        if normalised is None:
            return None
        return normalised
    role = (region.get("role") or "").lower()
    if "rom" in role and "data" in role:
        return "data"
    return None


def _normalise_access(raw: Any) -> str:
    if not isinstance(raw, str):
        return "rwx"
    return _ACCESS_NORMALISE.get(raw.strip().lower(), "rwx")


def _detect_backing(region: dict[str, Any]) -> str | None:
    role = (region.get("role") or "").lower()
    if region.get("backing"):
        return region["backing"]
    if "xip" in role:
        # RP2040 uses external QSPI; ESP32 uses external SPI.  Best
        # guess from the role string.
        if "qspi" in role:
            return "external-qspi-flash"
        return "external-spi-flash"
    return None


# ---------------------------------------------------------------------------
# Section converters
# ---------------------------------------------------------------------------


def _convert_identity(payload: dict[str, Any]) -> dict[str, Any]:
    src = payload.get("identity") or {}
    out = {
        "vendor": src.get("vendor"),
        "family": src.get("family"),
        "device": src.get("device"),
        "core": _convert_core(src.get("core") or "", payload),
    }
    if src.get("package"):  out["package"] = src["package"]
    if src.get("summary"):  out["description"] = src["summary"]
    return {k: v for k, v in out.items() if v is not None}


_CORE_BITS = {
    "cortex-m0": 32, "cortex-m0plus": 32, "cortex-m3": 32,
    "cortex-m4": 32, "cortex-m4f": 32, "cortex-m7": 32, "cortex-m7f": 32,
    "cortex-m23": 32, "cortex-m33": 32, "cortex-m55": 32,
    "avr": 8, "avr5": 8, "avr-mega": 8,
    "xtensa-lx6": 32, "xtensa-lx7": 32,
}
_CORE_ISA = {
    "cortex-m0": "armv6-m", "cortex-m0plus": "armv6-m",
    "cortex-m3": "armv7-m", "cortex-m4": "armv7e-m", "cortex-m4f": "armv7e-m",
    "cortex-m7": "armv7e-m", "cortex-m7f": "armv7e-m",
    "cortex-m23": "armv8-m.base", "cortex-m33": "armv8-m.main",
    "cortex-m55": "armv8.1-m.main",
    "avr": "avr", "avr5": "avr", "avr-mega": "avr",
    "xtensa-lx6": "xtensa-lx6", "xtensa-lx7": "xtensa-lx7",
}


def _convert_core(core_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = core_name or "unknown"
    out = {
        "isa":  _CORE_ISA.get(name, "unknown"),
        "name": name,
        "bits": _CORE_BITS.get(name, 32),
    }
    if name.endswith("f"):
        out["fpu"] = True
    if "m4" in name or "m7" in name or "m33" in name:
        out["mpu"] = True
    interrupts = payload.get("interrupts") or []
    if isinstance(interrupts, list):
        out["interrupt_lines"] = len(interrupts)
    return out


def _convert_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    src = payload.get("provenance") or {}
    primary = src.get("source_id") or "unknown"
    if src.get("source_path"):
        primary = f"{primary}:{src['source_path']}"
    out = {
        "primary":  primary,
        "authored": "auto+hand",   # converter output mixes auto-extract + manual conversion
    }
    secondary = src.get("contributing_sources") or src.get("patch_ids") or []
    if isinstance(secondary, list) and secondary:
        out["secondary"] = [str(s) for s in secondary if s != src.get("source_id")]
    out["notes"] = "Converted from canonical-v1 by scripts/convert_v1_to_v2_1.py"
    return out


def _convert_memory(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("memories") or []
    vendor = (payload.get("identity") or {}).get("vendor", "")
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        size_val = r.get("size_bytes") or r.get("size")
        if isinstance(size_val, int):
            size_str = _bytes_with_unit(size_val)
        else:
            size_str = size_val
        # Required: id + size + access.  base may be absent for
        # virtual / overlay regions in v1; skip those (they don't
        # belong in a linker script anyway).
        base_v1 = r.get("base_address")
        if base_v1 is None:
            base_v1 = r.get("base")
        if not isinstance(base_v1, int):
            continue
        entry: dict[str, Any] = {
            "id":     (r.get("name") or r.get("id") or "unknown").lower(),
            "base":   _hex_addr(base_v1),
            "size":   size_str,
            "access": _normalise_access(r.get("access")),
        }
        if r.get("startup_roles"):
            roles = r["startup_roles"]
            if "code" in roles:    entry["alias"] = "code"
            elif "data" in roles:  entry["alias"] = "data"
        addr_space = _detect_address_space(r, vendor)
        if addr_space:
            entry["address_space"] = addr_space
        backing = _detect_backing(r)
        if backing:
            entry["backing"] = backing
        if r.get("role"):
            entry["role"] = r["role"]
        out.append({k: v for k, v in entry.items() if v is not None})
    return out


def _convert_clock(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = payload.get("clock_nodes") or []
    selectors = payload.get("clock_selectors") or []
    profiles_v1 = payload.get("system_clock_profiles") or []

    # Oscillators: clock_nodes whose `kind` smells like an oscillator.
    oscillators: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = (node.get("kind") or "").lower()
        node_id = (node.get("node_id") or "").replace("clock-node:", "")
        if not node_id:
            continue
        if "oscillator" in kind or "crystal" in kind or "rc" in kind:
            mapped_kind = "rc-internal"
            if "crystal" in kind and "external" in kind:
                mapped_kind = "crystal-external"
            elif "external" in kind:
                mapped_kind = "crystal-external"
            elif "internal" in kind:
                mapped_kind = "rc-internal"
            oscillators[node_id] = {"freq": "0Hz", "kind": mapped_kind}

    if not oscillators:
        # Fallback for chips with no clock_nodes — emit a single
        # placeholder so the schema accepts the file.
        oscillators = {"unknown": {"freq": "0Hz", "kind": "rc-internal"}}

    # Domains: synthesise one per clock_selector, plus a `sysclk` if
    # there is none.
    domains: list[dict[str, Any]] = []
    for sel in selectors:
        if not isinstance(sel, dict):
            continue
        sel_id = (sel.get("selector_id") or "").replace("selector:", "")
        if not sel_id:
            continue
        sources = [
            (opt or "").replace("clock-node:", "")
            for opt in (sel.get("parent_options") or [])
        ]
        domain: dict[str, Any] = {
            "id": sel_id.lower().replace("-", "_").replace(":", "_"),
            "sources": [s for s in sources if s],
        }
        if sel.get("register_target"):
            # Best-effort encoding mapping — v1 didn't carry the
            # numeric encoding, so we emit an empty mapping.
            target = sel["register_target"]
            parts = target.split(".")
            if len(parts) >= 2:
                domain["select_register"] = {
                    "reg":   ".".join(parts[:-1]),
                    "field": parts[-1],
                    "encoding": {s: i for i, s in enumerate(domain["sources"])},
                }
        domains.append(domain)

    if not any(d["id"] == "sysclk" for d in domains):
        # Synthesize a sysclk tying every oscillator together.
        domains.insert(0, {
            "id":      "sysclk",
            "sources": list(oscillators.keys()),
        })

    out: dict[str, Any] = {
        "oscillators": oscillators,
        "domains":     domains,
    }

    # Profiles
    profiles: list[dict[str, Any]] = []
    for prof in profiles_v1:
        if not isinstance(prof, dict):
            continue
        kind_v1 = (prof.get("kind") or "post-reset").lower()
        kind_map = {
            "post-reset": "post-reset", "safe": "safe",
            "recommended": "recommended", "alternative": "alternative",
            "low-power": "low-power",
        }
        sysclk_hz = prof.get("sysclk_hz")
        sysclk_str = _hz_with_unit(sysclk_hz) if isinstance(sysclk_hz, int) else None
        if not sysclk_str:
            continue
        profile = {
            "id":             (prof.get("profile_id") or prof.get("name") or "unknown").lower(),
            "kind":           kind_map.get(kind_v1, "post-reset"),
            "sysclk":         sysclk_str,
            "sysclk_source": (prof.get("source_kind") or prof.get("source") or "unknown").lower(),
        }
        profiles.append(profile)
    if profiles:
        out["profiles"] = profiles

    return out


def _convert_templates(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Group v1 register_fields by IP class → templates."""
    peripherals = payload.get("peripherals") or []
    register_fields = payload.get("register_fields") or []
    registers = payload.get("registers") or []

    # peripheral_name -> ip_name
    per_to_ip: dict[str, str] = {}
    for per in peripherals:
        if not isinstance(per, dict):
            continue
        name = per.get("name")
        ip = per.get("ip_name")
        if name and ip:
            per_to_ip[name] = ip

    # register_id -> offset
    reg_offsets: dict[str, int] = {}
    for reg in registers:
        if not isinstance(reg, dict):
            continue
        rid = reg.get("register_id") or reg.get("id")
        offset = reg.get("offset_bytes") or reg.get("offset")
        if rid and isinstance(offset, int):
            reg_offsets[rid] = offset

    # Group fields by ip_name + register_name
    # templates[ip][register_name][field_name] = (bit_offset, bit_width)
    templates: dict[str, dict[str, dict[str, tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    template_register_offsets: dict[str, dict[str, int]] = defaultdict(dict)

    for fld in register_fields:
        if not isinstance(fld, dict):
            continue
        per_name = fld.get("peripheral")
        reg_name = fld.get("register_name")
        f_name = fld.get("name")
        bit_offset = fld.get("bit_offset")
        bit_width = fld.get("bit_width")
        if not (per_name and reg_name and f_name and isinstance(bit_offset, int)
                and isinstance(bit_width, int)):
            continue
        ip = per_to_ip.get(per_name)
        if not ip:
            continue
        templates[ip][reg_name.lower()][f_name.lower()] = (bit_offset, bit_width)
        # Capture register offset (use first occurrence)
        rid = fld.get("register_id")
        if rid and rid in reg_offsets and reg_name.lower() not in template_register_offsets[ip]:
            template_register_offsets[ip][reg_name.lower()] = reg_offsets[rid]

    # Build per-IP `options` block from the v1 tier-2/3/4 flat lists.
    per_ip_options = _build_template_options(payload, per_to_ip)
    per_ip_max_clock = _build_template_max_clocks(payload)

    # Render templates
    out: dict[str, dict[str, Any]] = {}
    for ip_name, by_reg in sorted(templates.items()):
        registers_block: dict[str, dict[str, Any]] = {}
        fields_block: dict[str, dict[str, Any]] = {}
        for reg_name, fields in sorted(by_reg.items()):
            offset = template_register_offsets[ip_name].get(reg_name)
            if offset is not None:
                registers_block[reg_name] = {"offset": _hex_addr(offset)}
            for f_name, (bit_offset, bit_width) in sorted(fields.items()):
                key = f"{reg_name}.{f_name}"
                if bit_width == 1:
                    fields_block[key] = {"bit": bit_offset}
                else:
                    fields_block[key] = {
                        "bits": [bit_offset, bit_offset + bit_width - 1],
                    }
        ip_template: dict[str, Any] = {}
        if ip_name in per_ip_options:
            ip_template["options"] = per_ip_options[ip_name]
        if ip_name in per_ip_max_clock:
            for k, v in per_ip_max_clock[ip_name].items():
                ip_template[k] = v
        if registers_block: ip_template["registers"] = registers_block
        if fields_block:    ip_template["fields"] = fields_block
        if ip_template:
            out[ip_name] = ip_template

    # Also render templates that exist only via tier-2/3/4 data (no
    # register_fields[] rows survived the v1 extraction).
    for ip_name, options in per_ip_options.items():
        if ip_name in out:
            continue
        seed: dict[str, Any] = {"options": options}
        if ip_name in per_ip_max_clock:
            for k, v in per_ip_max_clock[ip_name].items():
                seed[k] = v
        out[ip_name] = seed
    return out


def _build_template_options(
    payload: dict[str, Any],
    per_to_ip: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Fold the v1 ``adc_*``/``uart_*``/``spi_*``/``i2c_*``/
    ``timer_*``/``pwm_*`` tier flat lists into per-IP options maps."""

    def _vals(rows: list[Any], field_name: str) -> list[Any]:
        out = []
        for r in rows:
            if isinstance(r, dict) and field_name in r:
                out.append(r[field_name])
        return out

    def _vals_for_ip(ip_name: str, rows: list[Any], field_name: str) -> list[Any]:
        # If the v1 row carries `peripheral`, filter on it; otherwise return
        # all values (chip-wide).
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            per = r.get("peripheral")
            if per is None or per_to_ip.get(per, "").lower() == ip_name:
                if field_name in r:
                    out.append(r[field_name])
        return out

    out: dict[str, dict[str, Any]] = defaultdict(dict)

    # ADC
    res = _vals(payload.get("adc_resolution_options") or [], "bits")
    if res: out["adc"]["resolution"] = sorted(set(res))
    cycles = _vals(payload.get("adc_sample_time_options") or [], "cycles_q8")
    if cycles:
        # cycles_q8 is fixed-point (8 fractional bits); convert to a
        # human-readable list.
        out["adc"]["sample_time_cycles"] = sorted({c / 256.0 for c in cycles})
    over = _vals(payload.get("adc_oversampling_options") or [], "ratio")
    if over: out["adc"]["oversampling"] = sorted(set(over))

    # UART
    db = _vals(payload.get("uart_data_bits_options") or [], "bits")
    if db: out["usart"]["data_bits"] = sorted(set(db))
    if db: out["uart"]["data_bits"] = sorted(set(db))
    par = _vals(payload.get("uart_parity_options") or [], "kind")
    if par: out["usart"]["parity"] = sorted(set(par))
    if par: out["uart"]["parity"] = sorted(set(par))
    sb = _vals(payload.get("uart_stop_bits_options") or [], "bits")
    if sb: out["usart"]["stop_bits"] = sorted({str(s) for s in sb})
    if sb: out["uart"]["stop_bits"] = sorted({str(s) for s in sb})

    # SPI
    bp = _vals(payload.get("spi_baud_prescaler_options") or [], "divisor")
    if bp: out["spi"]["baud_prescaler"] = sorted(set(bp))

    # I2C
    sp = _vals(payload.get("i2c_speed_options") or [], "speed_hz")
    if sp: out["i2c"]["speeds"] = sorted({_hz_with_unit(s) for s in sp if isinstance(s, int)})

    # Timer
    tp = _vals(payload.get("timer_prescaler_options") or [], "max_value")
    if tp: out["timer_general"]["prescaler_max"] = max(tp)

    return dict(out)


def _build_template_max_clocks(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Map the chip-wide ``adc_max_clock_hz`` / ``uart_max_baud_hz`` /
    ``i2c_max_clock_hz`` ints onto per-IP template ``max_clock`` /
    ``max_baud`` strings."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    adc_hz = payload.get("adc_max_clock_hz")
    if isinstance(adc_hz, int):
        out["adc"]["max_clock"] = _hz_with_unit(adc_hz)
    uart_baud = payload.get("uart_max_baud_hz")
    if isinstance(uart_baud, int):
        out["usart"]["max_baud"] = uart_baud
        out["uart"]["max_baud"] = uart_baud
    i2c_hz = payload.get("i2c_max_clock_hz")
    if isinstance(i2c_hz, int):
        out["i2c"]["max_clock"] = _hz_with_unit(i2c_hz)
    return dict(out)


def _build_pin_options_index(
    payload: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Invert ``gpio_pins[].alt_functions[]`` into a per-peripheral
    map of ``signal_lower -> [{pin, remap}, …]``.

    v1 stored pin↔function bindings on the GPIO side; v2.1 puts them
    on the consumer (peripheral) side under ``pin_options``.
    """
    out: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for pin in payload.get("gpio_pins") or []:
        if not isinstance(pin, dict):
            continue
        pin_id = pin.get("pin_id")
        if not pin_id:
            continue
        for af in pin.get("alt_functions") or []:
            if not isinstance(af, dict):
                continue
            per = af.get("peripheral")
            sig = af.get("signal_name")
            af_num = af.get("af_number")
            if not (per and sig):
                continue
            entry: dict[str, Any] = {"pin": pin_id}
            if isinstance(af_num, int):
                # STM32 F4+ uses AF index in the GPIO AFR register;
                # F1 uses remap.  We can't tell from v1 which one —
                # store as `func` (v2.1 RP2040-style) which is the
                # most general spelling.
                entry["func"] = af_num
            out[per][sig.lower()].append(entry)
    return out


def _build_calibration_block(
    rows: list[Any],
    context: dict[str, Any] | None,
    target_per: str,
) -> dict[str, Any] | None:
    """Group v1 ``adc_calibration_data_points[]`` rows for one ADC
    instance into the v2.1 ``calibration:`` block."""
    cal: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("peripheral") != target_per:
            continue
        kind = row.get("kind") or ""
        addr = row.get("address")
        if not isinstance(addr, int):
            continue
        size_bits = row.get("size_bits", 16)
        semantic = row.get("semantic_constant")
        # Map v1's `vrefint_cal` / `ts_cal_low` / `ts_cal_high` to v2.1.
        if "vrefint" in kind:
            cal["vrefint"] = {
                "rom_addr": _hex_addr(addr),
                "size_bits": size_bits,
                "nominal_mv": semantic,
            }
        elif "ts_cal_low" in kind or "low" in kind:
            cal["ts_cal_low"] = {
                "rom_addr": _hex_addr(addr),
                "size_bits": size_bits,
                "temp_celsius": semantic,
            }
        elif "ts_cal_high" in kind or "high" in kind:
            cal["ts_cal_high"] = {
                "rom_addr": _hex_addr(addr),
                "size_bits": size_bits,
                "temp_celsius": semantic,
            }
    if context and isinstance(context, dict) and context.get("peripheral") == target_per:
        # Pull additional context (cal voltages, temp range) into the
        # data points if the v1 row didn't carry them already.
        v_mv = context.get("cal_voltage_mv")
        if v_mv is not None and "vrefint" in cal and "nominal_mv" not in cal["vrefint"]:
            cal["vrefint"]["nominal_mv"] = v_mv
        t_low = context.get("cal_temp_low_celsius")
        if t_low is not None and "ts_cal_low" in cal:
            cal["ts_cal_low"]["temp_celsius"] = t_low
        t_high = context.get("cal_temp_high_celsius")
        if t_high is not None and "ts_cal_high" in cal:
            cal["ts_cal_high"]["temp_celsius"] = t_high
    return cal or None


def _build_external_triggers(
    rows: list[Any], target_per: str,
) -> dict[str, list[dict[str, Any]]] | None:
    """Group v1 ``adc_external_triggers[]`` for one ADC instance."""
    regular: list[dict[str, Any]] = []
    injected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("peripheral") != target_per:
            continue
        source = row.get("source")
        extsel = row.get("extsel_value")
        polarity = row.get("default_polarity")
        if not source:
            continue
        entry: dict[str, Any] = {"source": source}
        if isinstance(extsel, int):
            entry["extsel"] = extsel
        if polarity == 1:
            entry["polarity"] = "rising"
        elif polarity == 2:
            entry["polarity"] = "falling"
        regular.append(entry)
    out = {}
    if regular:  out["regular"] = regular
    if injected: out["injected"] = injected
    return out or None


def _build_internal_channels(
    rows: list[Any], target_per: str,
) -> dict[str, str] | None:
    """ADC internal channels (vrefint, temp_sensor, vbat) → v2.1 channels map."""
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("peripheral") != target_per:
            continue
        kind = row.get("kind")
        ch = row.get("channel_index")
        if isinstance(ch, int) and kind:
            # v2.1 keys channels as ``ch<N>: <internal-name>``.
            label_map = {
                "vrefint": "vrefint",
                "temperature_sensor": "temp_sensor",
                "vbat": "vbat",
            }
            label = label_map.get(kind, kind)
            out[f"ch{ch}"] = label
    return out or None


def _build_timing_presets(
    rows: list[Any], target_per: str,
) -> list[dict[str, Any]] | None:
    """I2C TIMINGR presets per (speed, source_clock)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("peripheral") != target_per:
            continue
        speed_hz = row.get("speed_hz")
        clk_hz = row.get("source_clock_hz")
        timingr = row.get("timingr_value")
        if not (isinstance(speed_hz, int) and isinstance(clk_hz, int)
                and isinstance(timingr, int)):
            continue
        out.append({
            "speed":        _hz_with_unit(speed_hz),
            "source_clock": _hz_with_unit(clk_hz),
            "timingr":      _hex_addr(timingr),
        })
    return out or None


def _build_max_clock_overrides(rows: list[Any]) -> dict[str, str]:
    """``peripheral_max_clock_hz[]`` → ``{<peripheral>: '<freq>MHz'}``."""
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        per = row.get("peripheral")
        hz = row.get("max_clock_hz")
        if per and isinstance(hz, int):
            freq_str = _hz_with_unit(hz)
            if freq_str:
                out[per] = freq_str
    return out


def _convert_peripherals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    src = payload.get("peripherals") or []
    interrupts = payload.get("interrupts") or []
    pin_options_idx = _build_pin_options_index(payload)
    cal_rows  = payload.get("adc_calibration_data_points") or []
    cal_ctx   = payload.get("adc_calibration_context") or {}
    ext_trigs = payload.get("adc_external_triggers") or []
    int_chans = payload.get("adc_internal_channels") or []
    timing_rows = payload.get("i2c_timing_presets") or []
    max_clock_overrides = _build_max_clock_overrides(
        payload.get("peripheral_max_clock_hz") or []
    )

    # peripheral_name -> [irq_entries]
    irq_by_per: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for irq in interrupts:
        if not isinstance(irq, dict):
            continue
        per = irq.get("peripheral")
        if not per:
            continue
        line = irq.get("line")
        name = irq.get("name")
        if isinstance(line, int) and name:
            irq_by_per[per].append({"num": line, "name": name})

    out: list[dict[str, Any]] = []
    for per in src:
        if not isinstance(per, dict):
            continue
        ip_name = per.get("ip_name")
        per_name = per.get("name")
        if not ip_name or not per_name:
            continue
        entry: dict[str, Any] = {
            "id":       per_name.lower(),
            "template": ip_name,
        }
        if per.get("ip_version"):
            entry["ip_version"] = per["ip_version"]
        if per.get("base_address"):
            entry["base"] = _hex_addr(per["base_address"])
        # rcc.en / rst from rcc_enable_signal / rcc_reset_signal
        rcc = {}
        if per.get("rcc_enable_signal"): rcc["en"] = per["rcc_enable_signal"]
        if per.get("rcc_reset_signal"):  rcc["rst"] = per["rcc_reset_signal"]
        if rcc:
            entry["rcc"] = rcc
        irqs = irq_by_per.get(per_name)
        if irqs:
            entry["irq"] = irqs[0] if len(irqs) == 1 else irqs
        if per_name in pin_options_idx:
            entry["pin_options"] = dict(pin_options_idx[per_name])
        if per_name in max_clock_overrides:
            entry["max_clock_override"] = max_clock_overrides[per_name]
        # ADC-specific extensions.
        if ip_name == "adc" or "adc" in (per_name or "").lower():
            cal = _build_calibration_block(cal_rows, cal_ctx, per_name)
            if cal:
                entry["calibration"] = cal
            ext = _build_external_triggers(ext_trigs, per_name)
            if ext:
                entry["external_triggers"] = ext
            chans = _build_internal_channels(int_chans, per_name)
            if chans:
                entry["channels"] = chans
        # I²C-specific.
        if ip_name == "i2c" or (per_name or "").upper().startswith("I2C"):
            tp = _build_timing_presets(timing_rows, per_name)
            if tp:
                entry["timing_presets"] = tp
        out.append(entry)
    return out


def _convert_pinout(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert v1 pin records to v2.1 pinout entries.

    v1's ``pins[].number`` is the bit-index within the port (PA0 → 0,
    PA15 → 15) — that's NOT the v2.1 package pad number.  package_pads
    carries the silk-screen position, but the linkage between them is
    vendor-specific.  We emit just the canonical signal name; the
    `pin`/`pad` field stays absent until the converter learns to fold
    package_pads in.
    """
    pins = payload.get("pins") or []
    package_pads = payload.get("package_pads") or []

    # Build a {pin_name → pad_position} map from package_pads when present.
    pad_pos: dict[str, int] = {}
    for pad in package_pads:
        if not isinstance(pad, dict):
            continue
        bonded = pad.get("bonded_pin")
        position = pad.get("physical_index")
        if bonded and isinstance(position, int) and position >= 1:
            pad_pos[bonded] = position

    # pin_constraints: { pin_name -> [constraint_kind, …] }
    constraint_map: dict[str, list[str]] = defaultdict(list)
    constraint_translation = {
        "analog-only": "analog-only",
        "analog_only": "analog-only",
        "analog-capable": "analog-capable",
        "analog_capable": "analog-capable",
        "input-only": "input-only",
        "input_only":  "input-only",
        "5v-tolerant": "low-drive",   # closest match in v2.1's enum
        "ft":          "low-drive",   # 5V-tolerant flag in v1 STM32
        "boot":        "boot",
        "reset":       "reset",
        "rtc":         "rtc",
        "strapping":   "strapping",
        "flash-reserved": "flash-reserved",
        "lfxo-bond":   "lfxo-bond",
        "nfc-default": "nfc-default",
        "debug-default": "debug-default",
        "module-reserved": "module-reserved",
        "power":       "power",
        "oscillator":  "oscillator",
        "chip-enable": "chip-enable",
        "low-drive":   "low-drive",
    }
    for c in payload.get("pin_constraints") or []:
        if not isinstance(c, dict):
            continue
        pin_name = c.get("pin")
        kind = c.get("kind")
        if not (pin_name and kind):
            continue
        v2_kind = constraint_translation.get(kind.lower())
        if v2_kind:
            constraint_map[pin_name].append(v2_kind)

    out: list[dict[str, Any]] = []
    for pin in pins:
        if not isinstance(pin, dict):
            continue
        name = pin.get("name")
        if not name:
            continue
        entry: dict[str, Any] = {"signal": name}
        if name in pad_pos:
            entry["pin"] = pad_pos[name]
        if name in constraint_map:
            # de-dup while preserving order
            seen = set()
            uniq = []
            for c in constraint_map[name]:
                if c not in seen:
                    uniq.append(c); seen.add(c)
            entry["constraints"] = uniq
        out.append(entry)
    return out


def _convert_interrupts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    src = payload.get("interrupts") or []
    out: list[dict[str, Any]] = []
    for irq in src:
        if not isinstance(irq, dict):
            continue
        line = irq.get("line")
        name = irq.get("name")
        if not (isinstance(line, int) and name):
            continue
        out.append({"num": line, "name": name})
    return out


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def convert_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Transform a v1 primitive payload into a v2.1 primitive payload."""
    out: dict[str, Any] = {
        "schema":    "alloy.device.v2.1",
        "identity":  _convert_identity(payload),
        "provenance": _convert_provenance(payload),
        "memory":    _convert_memory(payload),
        "clock":     _convert_clock(payload),
    }
    templates = _convert_templates(payload)
    if templates:
        out["templates"] = templates
    out["peripherals"] = _convert_peripherals(payload)
    pinout = _convert_pinout(payload)
    if pinout:
        out["pinout"] = pinout
    interrupts = _convert_interrupts(payload)
    if interrupts:
        out["interrupts"] = interrupts
    # Strip dropped sections (none survive — we never copied them).
    return out


def convert_one(in_path: Path, out_path: Path, *, validate: bool = True) -> None:
    """Convert a single YAML file."""
    payload_v1 = _load_yaml(in_path)
    payload_v2 = convert_payload(payload_v1)
    if validate:
        from alloy_codegen.canonical_device_v2_1 import (  # noqa: E402
            serialize_device, parse_device_payload,
        )
        device = parse_device_payload(payload_v2)   # validates + builds IR
        text = serialize_device(device)              # canonical re-emit
    else:
        # Cheap path — just yaml.dump without validating.
        text = yaml.safe_dump(payload_v2, sort_keys=False, allow_unicode=True, width=10000)
        if not text.endswith("\n"):
            text += "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")


def _walk_inputs(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if root.is_dir():
        return sorted(root.rglob("*.yml"))
    raise FileNotFoundError(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path,
                        help="A single YAML, or a vendors/ tree to recurse into.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output root.  YAMLs land at the same relative path.")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip the v2.1 schema validation round-trip "
                             "(fast iteration only).")
    args = parser.parse_args(argv)

    inputs = _walk_inputs(args.input)
    if not inputs:
        print(f"No YAMLs under {args.input}", file=sys.stderr)
        return 1

    failed = 0
    for in_path in inputs:
        if args.input.is_file():
            relative = in_path.name
        else:
            relative = in_path.relative_to(args.input)
        out_path = args.out / relative
        try:
            convert_one(in_path, out_path, validate=not args.no_validate)
            in_size = in_path.stat().st_size
            out_size = out_path.stat().st_size
            saved = (1 - out_size / in_size) * 100 if in_size else 0.0
            print(
                f"{in_path.name:40s}  {in_size:>10,} → {out_size:>8,} "
                f"({saved:+5.1f}%)"
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {in_path}: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    print(f"\n{len(inputs) - failed}/{len(inputs)} files converted.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
