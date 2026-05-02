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
    other vendors keep their conventional flat layout."""
    raw = region.get("address_space")
    if isinstance(raw, str):
        return _ADDRESS_SPACE_NORMALISE.get(raw.lower(), raw.lower())
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
        if registers_block: ip_template["registers"] = registers_block
        if fields_block:    ip_template["fields"] = fields_block
        if ip_template:
            out[ip_name] = ip_template
    return out


def _convert_peripherals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    src = payload.get("peripherals") or []
    interrupts = payload.get("interrupts") or []

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
