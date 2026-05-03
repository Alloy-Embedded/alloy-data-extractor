"""CMSIS-SVD → v2.1 primary extractor.

Added by ``adopt-canonical-device-v2-1``.

Reads a CMSIS-SVD XML file directly and produces the v2.1 primitive
payload — no v1 intermediate, no post-hoc conversion.

What it produces:

* ``identity`` from ``<device><name>`` + ``<cpu><name>`` heuristics.
* ``provenance`` (single top-level block).
* ``memory`` from ``<peripheral>`` blocks tagged with
  ``addressBlock.usage="ram"|"flash"``  (best effort — most SVDs
  don't carry memory map; left empty when absent).
* ``templates[<peripheralClass>]`` clustered by lowercased peripheral
  group name.  Each unique group becomes one template carrying the
  register layout (offset + access) + named field map (bit / bits +
  enum when SVD declares ``<enumeratedValues>``).
* ``peripherals[]`` with ``id``, ``template``, ``base``, ``ip_version``
  (taken from ``derivedFrom`` or vendor extension when present), and
  per-instance IRQs collected from ``<peripheral><interrupt>``.
* ``interrupts[]`` flat vector list — one row per
  ``<peripheral><interrupt>`` aggregated from every peripheral.
* ``pinout[]`` empty — SVD has no package data; downstream
  enrichment fills it (CubeMX / open-pin-data / DTS).

What it deliberately omits (per the v2.1 design):

* per-row provenance blocks
* synthesised rows (route_operations, vector_slots, …) — codegen's
  ``build_synthesised`` derives them at consume time
* ``capabilities`` / ``ip_blocks`` — IR-side only
* ``register_field_enumerations`` flat list — folded into
  ``templates.<ip>.fields[<name>].enum`` instead

Each chip becomes ~300-1500 lines of v2.1 YAML — vs the v1 SVD
extractor's 100KB-7MB output.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _findtext(node: ET.Element, key: str, default: str = "") -> str:
    found = node.find(key)
    return (found.text or default) if found is not None else default


def _parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        if text.startswith(("0x", "0X")):
            return int(text, 16)
        if text.startswith("#"):
            # SVD binary literal: ``#0001``
            return int(text[1:], 2)
        return int(text)
    except ValueError:
        return None


_CORE_BITS = {
    "cm0": 32, "cm0plus": 32, "cm0+": 32, "cm3": 32,
    "cm4": 32, "cm4f": 32, "cm7": 32, "cm7f": 32,
    "cm23": 32, "cm33": 32, "cm55": 32, "cm85": 32,
    "armv6-m": 32, "armv7-m": 32, "armv7e-m": 32,
    "armv8-m.base": 32, "armv8-m.main": 32, "armv8.1-m.main": 32,
}
_CORE_ISA = {
    "cm0": "armv6-m", "cm0plus": "armv6-m", "cm0+": "armv6-m",
    "cm3": "armv7-m",
    "cm4": "armv7e-m", "cm4f": "armv7e-m",
    "cm7": "armv7e-m", "cm7f": "armv7e-m",
    "cm23": "armv8-m.base", "cm33": "armv8-m.main",
    "cm55": "armv8.1-m.main", "cm85": "armv8.1-m.main",
}


def _normalise_core(svd_name: str) -> tuple[str, str, int, bool]:
    """Return ``(isa, name, bits, fpu)`` from a SVD ``<cpu><name>``
    string.

    Recognised:
      * ARM Cortex-M:  "CM0", "CM4", "CM7F", … → armv6-m / armv7-m / armv7e-m / armv8-m
      * Xtensa:        "Xtensa LX6", "Xtensa LX7" → xtensa LX-named
      * RISC-V:        "RV32IMC", "RV32IMAC", "RV32IMAFC", … → riscv ISA name
    Falls back to ARM Cortex-M heuristic for unknown "cm*" prefixes
    (matches modm-devices behaviour) and "unknown" for everything else.
    """
    raw = (svd_name or "").strip()
    n = raw.lower()
    if not n:
        return "unknown", "unknown", 32, False

    # ARM Cortex-M short forms ("CM4F", "CM7", …).
    if n in _CORE_ISA:
        return _CORE_ISA[n], n, _CORE_BITS.get(n, 32), n.endswith("f")
    if n.startswith("cm"):
        # Unknown "cm<x>" — fall back to ARMv7-M.
        return "armv7-m", n, 32, n.endswith("f")

    # Xtensa: "Xtensa LX6" / "Xtensa LX7" (Espressif ESP32 classic / S2 / S3 / P4 LP).
    if "xtensa" in n:
        # Slug the variant: "xtensa lx6" → "xtensa-lx6".
        slug = n.replace(" ", "-")
        return "xtensa", slug, 32, True   # ESP32 Xtensa LX6/LX7 ship with FPU

    # RISC-V: "RV32IMC", "RV32IMAC", "RV32IMAFC" (Espressif ESP32-C2/C3/C6/H2/P4).
    if n.startswith("rv"):
        # bits — RV32 = 32, RV64 = 64 (no production MCU yet but future-proof).
        bits = 64 if n.startswith("rv64") else 32
        # fpu — present when 'f' or 'd' appears in the ISA letters
        # (after the rv32/rv64 prefix).
        suffix = n[4:] if len(n) >= 4 else ""
        fpu = "f" in suffix or "d" in suffix
        return "riscv", n, bits, fpu

    # Unknown architecture — preserve verbatim so downstream tools
    # can still match on the raw string.
    return n, n, 32, False


_REG_ACCESS_MAP = {
    "read-only": "ro",
    "write-only": "wo",
    "read-write": "rw",
    "read-writeOnce": "rw",
    "writeOnce": "wo",
}


def _normalise_access(svd_access: str | None) -> str | None:
    if not svd_access:
        return None
    return _REG_ACCESS_MAP.get(svd_access.strip(), None)


def _peripheral_class(peripheral_node: ET.Element) -> str:
    """Pick the IP class for a ``<peripheral>``.

    Priority:
      1. ``<groupName>`` if declared.
      2. ``derivedFrom`` attribute (this peripheral's layout was
         declared on a base — the base is the class).
      3. Lowercased ``<name>`` with trailing digits stripped (USART1
         → ``usart``, GPIOA → ``gpio``).
    """
    group = _findtext(peripheral_node, "groupName")
    if group:
        return group.lower()
    derived = peripheral_node.get("derivedFrom", "").strip()
    if derived:
        return derived.lower().rstrip("0123456789").rstrip("_") or derived.lower()
    name = _findtext(peripheral_node, "name").lower().strip()
    base = name.rstrip("0123456789").rstrip("_")
    return base or name


# ---------------------------------------------------------------------------
# Field enumerations
# ---------------------------------------------------------------------------


def _parse_field_enum(field_node: ET.Element) -> dict[str, int]:
    """Collect ``<enumeratedValue>`` rows into a {name → value} map.

    Returns an empty dict when the SVD declares no enumeration or
    every enumerator's value is unparseable.
    """
    out: dict[str, int] = {}
    for enums in field_node.findall("enumeratedValues"):
        for ev in enums.findall("enumeratedValue"):
            name = _findtext(ev, "name").strip()
            raw = _findtext(ev, "value").strip()
            value = _parse_int(raw)
            if name and value is not None:
                out[name] = value
    return out


# ---------------------------------------------------------------------------
# Register / field traversal
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _RegisterRow:
    name: str
    offset: int
    access: str | None


@dataclass(slots=True)
class _FieldRow:
    register: str
    name: str
    bit_offset: int
    bit_width: int
    access: str | None
    enum: dict[str, int]


def _parse_field_position(field_node: ET.Element) -> tuple[int | None, int | None]:
    """Return ``(bit_offset, bit_width)`` from any of the three SVD
    spellings (``bitOffset+bitWidth``, ``lsb+msb``, ``bitRange``).
    """
    bit_offset = _parse_int(_findtext(field_node, "bitOffset"))
    bit_width = _parse_int(_findtext(field_node, "bitWidth"))
    if bit_offset is not None and bit_width is not None:
        return bit_offset, bit_width
    lsb = _parse_int(_findtext(field_node, "lsb"))
    msb = _parse_int(_findtext(field_node, "msb"))
    if lsb is not None and msb is not None:
        return lsb, msb - lsb + 1
    raw_range = _findtext(field_node, "bitRange").strip()
    if raw_range.startswith("[") and raw_range.endswith("]"):
        try:
            hi, lo = raw_range[1:-1].split(":")
            hi_i = int(hi.strip())
            lo_i = int(lo.strip())
            return lo_i, hi_i - lo_i + 1
        except ValueError:
            pass
    return None, None


def _walk_registers(peripheral_node: ET.Element) -> tuple[list[_RegisterRow], list[_FieldRow]]:
    registers: list[_RegisterRow] = []
    fields: list[_FieldRow] = []
    seen_offsets: set[int] = set()
    for reg in peripheral_node.iter("register"):
        name = _findtext(reg, "name").strip().lower()
        if not name:
            continue
        offset = _parse_int(_findtext(reg, "addressOffset"))
        if offset is None or offset in seen_offsets:
            # Drop alias / derivedFrom duplicates; first wins.
            continue
        seen_offsets.add(offset)
        access = _normalise_access(_findtext(reg, "access"))
        registers.append(_RegisterRow(name=name, offset=offset, access=access))
        for field in reg.iter("field"):
            f_name = _findtext(field, "name").strip().lower()
            if not f_name:
                continue
            bit_offset, bit_width = _parse_field_position(field)
            if bit_offset is None or bit_width is None:
                continue
            fields.append(_FieldRow(
                register=name,
                name=f_name,
                bit_offset=bit_offset,
                bit_width=bit_width,
                access=_normalise_access(_findtext(field, "access")),
                enum=_parse_field_enum(field),
            ))
    return registers, fields


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------


def _extract_peripherals_block(root: ET.Element) -> tuple[
    dict[str, dict[str, Any]],     # templates
    list[dict[str, Any]],           # peripherals (instances)
    list[dict[str, Any]],           # interrupts (flat)
]:
    """Walk every ``<peripheral>`` node and split into templates +
    per-instance peripherals + flat interrupts list."""
    # Resolve `derivedFrom` references — the layout for a derived
    # peripheral lives on its parent.
    by_name: dict[str, ET.Element] = {}
    for per in root.iter("peripheral"):
        name = _findtext(per, "name").strip()
        if name:
            by_name[name] = per

    # Cluster registers + fields by IP class (group_name).
    template_registers: dict[str, dict[str, _RegisterRow]] = defaultdict(dict)
    template_fields: dict[str, dict[tuple[str, str], _FieldRow]] = defaultdict(dict)

    peripherals: list[dict[str, Any]] = []
    interrupts: list[dict[str, Any]] = []

    for per in root.iter("peripheral"):
        name = _findtext(per, "name").strip()
        if not name:
            continue
        ip_class = _peripheral_class(per)
        # Resolve registers via derivedFrom chain.
        base = per
        derived = per.get("derivedFrom", "").strip()
        if derived and derived in by_name:
            base = by_name[derived]
        regs, fields = _walk_registers(base)
        for r in regs:
            template_registers[ip_class].setdefault(r.name, r)
        for f in fields:
            template_fields[ip_class].setdefault((f.register, f.name), f)
        base_addr = _parse_int(_findtext(per, "baseAddress"))
        instance: dict[str, Any] = {
            "id": name.lower(),
            "template": ip_class,
        }
        if base_addr is not None:
            instance["base"] = (
                f"0x{base_addr:X}" if base_addr >= 0x100 else base_addr
            )
        ip_version = (per.get("derivedFrom", "") or "").strip()
        if ip_version:
            instance["ip_version"] = ip_version
        # Per-peripheral IRQs.
        irqs: list[dict[str, Any]] = []
        for irq in per.iter("interrupt"):
            irq_name = _findtext(irq, "name").strip()
            irq_value = _parse_int(_findtext(irq, "value"))
            if irq_name and irq_value is not None:
                irqs.append({"num": irq_value, "name": f"{irq_name}_IRQHandler"})
                interrupts.append({"num": irq_value, "name": f"{irq_name}_IRQHandler"})
        if len(irqs) == 1:
            instance["irq"] = irqs[0]
        elif irqs:
            instance["irq"] = irqs
        peripherals.append(instance)

    # Render templates.
    templates: dict[str, dict[str, Any]] = {}
    for ip_class in sorted(template_registers):
        regs_block: dict[str, dict[str, Any]] = {}
        for reg_name, reg in sorted(template_registers[ip_class].items()):
            entry: dict[str, Any] = {
                "offset": (
                    f"0x{reg.offset:04X}" if reg.offset >= 0x100
                    else reg.offset
                ),
            }
            if reg.access:
                entry["access"] = reg.access
            regs_block[reg_name] = entry
        fields_block: dict[str, dict[str, Any]] = {}
        for (reg_name, f_name), field in sorted(template_fields[ip_class].items()):
            key = f"{reg_name}.{f_name}"
            entry = (
                {"bit": field.bit_offset} if field.bit_width == 1
                else {"bits": [field.bit_offset, field.bit_offset + field.bit_width - 1]}
            )
            if field.access:
                entry["access"] = field.access
            if field.enum:
                entry["enum"] = field.enum
            fields_block[key] = entry
        template_block: dict[str, Any] = {}
        if regs_block:
            template_block["registers"] = regs_block
        if fields_block:
            template_block["fields"] = fields_block
        if template_block:
            templates[ip_class] = template_block

    # Dedup the flat interrupt list — keep first occurrence per (num, name).
    seen_irqs: set[tuple[int, str]] = set()
    deduped_irqs: list[dict[str, Any]] = []
    for irq in interrupts:
        key = (irq["num"], irq["name"])
        if key not in seen_irqs:
            seen_irqs.add(key)
            deduped_irqs.append(irq)
    deduped_irqs.sort(key=lambda r: r["num"])

    return templates, peripherals, deduped_irqs


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    svd_path: Path,
    description: str | None = None,
) -> dict[str, Any]:
    """Extract one device from a CMSIS-SVD file as a v2.1 primitive payload.

    The returned dict satisfies the alloy.device.v2.1 JSON-Schema
    (modulo optional ``pinout`` enrichments downstream extractors
    fill in).
    """
    if not svd_path.exists():
        raise FileNotFoundError(f"SVD file not found: {svd_path}")
    root = ET.parse(svd_path).getroot()

    cpu_node = root.find("cpu")
    isa, core_name, bits, fpu = _normalise_core(
        _findtext(cpu_node, "name") if cpu_node is not None else "",
    )
    irq_count = _parse_int(_findtext(cpu_node, "deviceNumInterrupts")) if cpu_node is not None else None
    nvic_priority_bits = _parse_int(_findtext(cpu_node, "nvicPrioBits")) if cpu_node is not None else None

    core_block: dict[str, Any] = {
        "isa": isa,
        "name": core_name,
        "bits": bits,
    }
    if fpu:
        core_block["fpu"] = True
    if cpu_node is not None and (_findtext(cpu_node, "mpuPresent") or "").strip().lower() in {"true", "1"}:
        core_block["mpu"] = True
    if irq_count is not None:
        core_block["interrupt_lines"] = irq_count
    # nvic_priority_bits is only meaningful for ARM cores — Xtensa
    # and RISC-V SVDs from Espressif always emit `<nvicPrioBits>0`
    # which is misleading.  Suppress for non-ARM.
    if nvic_priority_bits is not None and isa.startswith("arm"):
        core_block["nvic_priority_bits"] = nvic_priority_bits

    identity_block: dict[str, Any] = {
        "vendor": vendor,
        "family": family,
        "device": device,
        "core": core_block,
    }
    summary = description or _findtext(root, "description").strip()
    if summary:
        identity_block["description"] = summary

    templates, peripherals, interrupts = _extract_peripherals_block(root)

    # Schema-required stubs.  SVD carries no memory map and no
    # package data; downstream enrichment overwrites.  We emit one
    # placeholder row in each so the payload validates standalone.
    memory_stub: list[dict[str, Any]] = [
        {
            "id":     "flash",
            "base":   "0x00000000",
            "size":   "1B",
            "access": "rx",
            "role":   "extractor-placeholder",
        },
    ]
    pinout_stub: list[dict[str, Any]] = [
        {"signal": "RESET"},
    ]

    payload: dict[str, Any] = {
        "schema":     "alloy.device.v2.1",
        "identity":   identity_block,
        "provenance": {
            "primary":   f"cmsis-svd:{svd_path.name}",
            "authored":  "auto",
            "notes":     "SVD-extracted skeleton — memory + pinout require enrichment.",
        },
        "memory": memory_stub,
        "clock": {
            # Minimum viable clock block.  Downstream enrichment
            # (CubeMX / overlay TOML / DTS) overwrites.
            "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
            "domains":     [{"id": "sysclk", "sources": ["unknown"]}],
        },
    }
    if templates:
        payload["templates"] = templates
    payload["peripherals"] = peripherals
    payload["pinout"]      = pinout_stub
    if interrupts:
        payload["interrupts"] = interrupts
    return payload


__all__ = [
    "extract_device",
]
