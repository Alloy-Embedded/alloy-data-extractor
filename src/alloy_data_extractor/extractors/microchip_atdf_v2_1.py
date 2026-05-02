"""Microchip ATDF → v2.1 primary extractor.

Added by ``adopt-canonical-device-v2-1`` follow-up: extends the v2.1
extractor surface from CMSIS-SVD (cmsis_svd_v2_1) to Microchip's
ATDF (Atmel Tools Device File) format used by AVR-* and SAM-*
device-family packs.

Key shape differences from SVD that this module handles:

* ``<address-spaces><memory-segment>`` carries Harvard ``program`` /
  ``data`` / ``eeprom`` / ``fuses`` / ``signatures`` regions
  explicitly — populated into v2.1 ``memory[]``.
* ``<modules><module>`` defines each IP class (one per AVR
  ``RTC``, ``USART``, ``TCA``, ``ADC``, …).
* ``<peripherals><module name="X"><instance name="Y"/>`` declares
  the per-instance binding (``Y`` is the silicon name; ``X`` is
  the module / IP class that gives us the v2.1 ``template``
  reference).
* ``<bitfield mask="0x06" name="…"/>`` carries the field's mask
  rather than a (bit, width) pair — we recompute lsb/msb from
  the mask.
* ``<value-group name="X"><value name="…" value="0x..."/></value-group>``
  is referenced from a ``<bitfield values="X"/>`` attribute,
  i.e. the enum lives separately and is looked up by name.
* ``<interrupts><interrupt index="N" module-instance="X" name="Y"/>``
  binds each NVIC slot to a peripheral instance.

Output shape: identical to ``cmsis_svd_v2_1.extract_device`` —
``alloy.device.v2.1`` primitive payload, schema-validatable
standalone.

Skips ``<value-group>`` lookups whose target is missing (some ATDF
files reference value-groups that aren't declared in the same
module) — the bit position survives even when the enum doesn't.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers (parse_int + access normalisation share semantics with SVD)
# ---------------------------------------------------------------------------


def _parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return int(text, 16) if text.startswith(("0x", "0X")) else int(text)
    except ValueError:
        return None


def _attr(node: ET.Element, key: str, default: str = "") -> str:
    return node.get(key, default) or default


_ATDF_RW_MAP = {
    "R": "ro", "W": "wo", "RW": "rw",
    "RO": "ro", "WO": "wo",
}


def _normalise_access(rw: str | None) -> str | None:
    if not rw:
        return None
    return _ATDF_RW_MAP.get(rw.strip().upper())


# ---------------------------------------------------------------------------
# Memory segment → v2.1 memory[] row
# ---------------------------------------------------------------------------


_ATDF_TYPE_TO_ADDRESS_SPACE = {
    "flash":              "program",
    "ram":                "data",
    "io":                 "data",
    "eeprom":             "eeprom",
    "fuses":              "fuse",
    "lockbits":           "fuse",
    "signatures":         "signature",
    "user_signatures":    "signature",
    "configuration_bits": "fuse",
}


def _segment_to_memory(segment: ET.Element, default_aspace: str) -> dict[str, Any] | None:
    name = _attr(segment, "name").lower()
    if not name:
        return None
    base = _parse_int(_attr(segment, "start"))
    size = _parse_int(_attr(segment, "size"))
    if base is None or size is None:
        return None
    seg_type = _attr(segment, "type").lower()
    address_space = _ATDF_TYPE_TO_ADDRESS_SPACE.get(
        seg_type, default_aspace,
    )
    rw = _attr(segment, "rw").upper() or "R"
    exec_flag = _attr(segment, "exec") == "1"
    if "W" in rw and exec_flag:
        access = "rwx"
    elif "W" in rw:
        access = "rw"
    elif "X" in rw or exec_flag:
        access = "rx"
    else:
        access = "ro"

    # Render size as bytes-with-unit; KB/MB/GB only when exact.
    # SAM E70 declares 512MB / 256MB peripheral regions which would
    # otherwise emit as "524288KB" — ugly and harder for downstream
    # tools.  Prefer the largest unit that divides exactly.
    if size >= (1 << 30) and size % (1 << 30) == 0:
        size_str = f"{size >> 30}GB"
    elif size >= (1 << 20) and size % (1 << 20) == 0:
        size_str = f"{size >> 20}MB"
    elif size >= 1024 and size % 1024 == 0:
        size_str = f"{size // 1024}KB"
    else:
        size_str = f"{size}B"

    out: dict[str, Any] = {
        "id":     name,
        "base":   f"0x{base:X}" if base >= 0x100 else base,
        "size":   size_str,
        "access": access,
    }
    if address_space:
        out["address_space"] = address_space
    return out


def _walk_memory(root: ET.Element) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for aspace in root.iter("address-space"):
        default = _attr(aspace, "id").lower()
        if default not in {"program", "data", "instruction"}:
            default = "data" if "data" in default else default or "data"
        for seg in aspace.iter("memory-segment"):
            row = _segment_to_memory(seg, default)
            if row is not None:
                out.append(row)
    return out


# ---------------------------------------------------------------------------
# Modules / templates / peripherals
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ATDFRegister:
    name: str
    offset: int
    access: str | None


@dataclass(slots=True)
class _ATDFField:
    register: str
    name: str
    bit_offset: int
    bit_width: int
    access: str | None
    enum: dict[str, int]


def _mask_to_bits(mask: int) -> tuple[int, int] | None:
    """Convert an ATDF ``mask=`` attribute into ``(lsb, width)``."""
    if mask <= 0:
        return None
    # First set bit
    lsb = (mask & -mask).bit_length() - 1
    # Width = number of set bits in the contiguous run
    width = (mask >> lsb).bit_length()
    # Sanity: contiguous mask?  Reject discontiguous bitfields (rare
    # in ATDF but possible) — we'd need a different IR shape.
    if (mask >> lsb) != ((1 << width) - 1):
        return None
    return lsb, width


def _resolve_value_group(
    module_node: ET.Element, vg_name: str,
) -> dict[str, int]:
    """Look up ``<value-group name="X">`` inside the module and
    return the (named-value → int) map.  Returns empty dict when
    the group is not declared."""
    if not vg_name:
        return {}
    for vg in module_node.iter("value-group"):
        if _attr(vg, "name") == vg_name:
            out: dict[str, int] = {}
            for v in vg.iter("value"):
                vname = _attr(v, "name")
                vraw = _parse_int(_attr(v, "value"))
                if vname and vraw is not None:
                    out[vname.lower()] = vraw
            return out
    return {}


def _walk_module(module_node: ET.Element) -> tuple[list[_ATDFRegister], list[_ATDFField]]:
    """Walk every ``<register>`` + ``<bitfield>`` under one
    ``<module>`` block and return flat lists.

    A module can have multiple ``<register-group>``s (e.g. PORTA
    declares one per logical sub-block).  We flatten — the caller
    treats them as a single template.
    """
    registers: list[_ATDFRegister] = []
    fields: list[_ATDFField] = []
    seen_offsets: set[int] = set()
    for reg in module_node.iter("register"):
        name = _attr(reg, "name").lower()
        offset = _parse_int(_attr(reg, "offset"))
        if not name or offset is None or offset in seen_offsets:
            continue
        seen_offsets.add(offset)
        access = _normalise_access(_attr(reg, "rw"))
        registers.append(_ATDFRegister(name=name, offset=offset, access=access))
        for bf in reg.iter("bitfield"):
            f_name = _attr(bf, "name").lower()
            mask = _parse_int(_attr(bf, "mask"))
            if not f_name or mask is None:
                continue
            bits = _mask_to_bits(mask)
            if bits is None:
                continue
            lsb, width = bits
            enum = _resolve_value_group(module_node, _attr(bf, "values"))
            fields.append(_ATDFField(
                register=name,
                name=f_name,
                bit_offset=lsb,
                bit_width=width,
                access=_normalise_access(_attr(bf, "rw")),
                enum=enum,
            ))
    return registers, fields


def _ip_class_for_module(module_name: str) -> str:
    """Lowercased module name without trailing digits.

    AVR's module names are already class-shaped (``USART``, ``TCA``,
    ``PORTA``) so we just lowercase + strip trailing digit groups."""
    return module_name.lower().rstrip("0123456789").rstrip("_") or module_name.lower()


def _extract_modules_block(root: ET.Element) -> tuple[
    dict[str, dict[str, Any]],     # templates
    list[dict[str, Any]],           # peripherals
    list[dict[str, Any]],           # interrupts (flat vector list)
]:
    """Walk ``<modules>`` + ``<peripherals>`` + ``<interrupts>``."""
    # Index modules by NAME (e.g. "USART") so per-instance lookups
    # find the right register layout.
    modules_by_name: dict[str, ET.Element] = {}
    for module in root.iter("modules"):
        for m in module.findall("module"):
            modules_by_name[_attr(m, "name")] = m

    # Cluster registers + fields by IP class.
    templates_by_class: dict[str, dict[str, Any]] = {}
    for mod_name, m in modules_by_name.items():
        ip_class = _ip_class_for_module(mod_name)
        regs, fields = _walk_module(m)
        if not regs and not fields:
            continue
        regs_block: dict[str, dict[str, Any]] = {}
        for r in regs:
            entry: dict[str, Any] = {
                "offset": f"0x{r.offset:X}" if r.offset >= 0x100 else r.offset,
            }
            if r.access:
                entry["access"] = r.access
            regs_block.setdefault(r.name, entry)
        fields_block: dict[str, dict[str, Any]] = {}
        for f in fields:
            key = f"{f.register}.{f.name}"
            if key in fields_block:
                continue
            entry = (
                {"bit": f.bit_offset} if f.bit_width == 1
                else {"bits": [f.bit_offset, f.bit_offset + f.bit_width - 1]}
            )
            if f.access:
                entry["access"] = f.access
            if f.enum:
                entry["enum"] = f.enum
            fields_block[key] = entry
        block: dict[str, Any] = {}
        if regs_block:
            block["registers"] = regs_block
        if fields_block:
            block["fields"] = fields_block
        if block:
            # Merge into the IP class — multiple AVR modules can map
            # to the same class (e.g. PORTA + PORTB → port).  We
            # union register / field dicts; first-write-wins on
            # collision.
            target = templates_by_class.setdefault(ip_class, {})
            for k, v in block.get("registers", {}).items():
                target.setdefault("registers", {}).setdefault(k, v)
            for k, v in block.get("fields", {}).items():
                target.setdefault("fields", {}).setdefault(k, v)

    # Per-instance peripherals
    peripherals: list[dict[str, Any]] = []
    instance_to_module: dict[str, str] = {}
    for per_root in root.iter("peripherals"):
        for module in per_root.findall("module"):
            mod_name = _attr(module, "name")
            ip_class = _ip_class_for_module(mod_name)
            for inst in module.findall("instance"):
                inst_name = _attr(inst, "name")
                if not inst_name:
                    continue
                instance_to_module[inst_name] = ip_class
                # Find a base address (first register-group offset).
                base = None
                rg = inst.find("register-group")
                if rg is not None:
                    base = _parse_int(_attr(rg, "offset"))
                row: dict[str, Any] = {
                    "id":       inst_name.lower(),
                    "template": ip_class,
                }
                if base is not None:
                    row["base"] = f"0x{base:X}" if base >= 0x100 else base
                peripherals.append(row)

    # Interrupts: flat vector list + per-peripheral cross-binding.
    interrupts: list[dict[str, Any]] = []
    seen_irq: set[tuple[int, str]] = set()
    irq_by_per: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for irq_root in root.iter("interrupts"):
        for irq in irq_root.iter("interrupt"):
            idx = _parse_int(_attr(irq, "index"))
            name = _attr(irq, "name")
            mod_inst = _attr(irq, "module-instance")
            if idx is None or not name:
                continue
            # SAM ATDFs include Cortex-M system exceptions
            # (Reset_vect=-15, NMI=-14, …, SysTick=-1) under
            # <interrupts>.  These are core-architectural, not
            # peripheral NVIC entries — the v2.1 schema requires
            # num >= 0.  Skip them; downstream consumers that need
            # the system-exception list can derive it from the core
            # ISA in identity.core.
            if idx < 0:
                continue
            full_name = f"{mod_inst}_{name}_vect" if mod_inst else f"{name}_vect"
            key = (idx, full_name)
            if key in seen_irq:
                continue
            seen_irq.add(key)
            entry = {"num": idx, "name": full_name}
            interrupts.append(entry)
            if mod_inst:
                irq_by_per[mod_inst].append(entry)
    interrupts.sort(key=lambda r: r["num"])

    # Attach IRQs back to their peripherals.
    for per in peripherals:
        irqs = irq_by_per.get(per["id"].upper())
        if irqs:
            per["irq"] = irqs[0] if len(irqs) == 1 else irqs

    return templates_by_class, peripherals, interrupts


# ---------------------------------------------------------------------------
# Identity / core
# ---------------------------------------------------------------------------


def _detect_core(root: ET.Element) -> dict[str, Any]:
    """ATDF doesn't carry a CMSIS-style ``<cpu>`` block — we infer
    from ``<device architecture>`` + the family slug.

    AVR8X = 8-bit AVR with extended core (AVR-DA, AVR-DB, AVR-DD, …);
    AVR8 = classic 8-bit AVR (ATmega, ATtiny);
    ARM* = various Cortex-M cores in SAM devices.
    """
    device = root.find(".//device")
    if device is None:
        return {"isa": "unknown", "name": "unknown", "bits": 8}
    arch = _attr(device, "architecture")
    family = _attr(device, "family").lower()
    a_lower = arch.lower()
    if a_lower.startswith("avr"):
        return {"isa": "avr", "name": f"avr-{family}" if family else "avr", "bits": 8}
    # Cortex-M7 (SAME70, SAMS70, SAMV70/V71) — Cortex-M7F with FPU + MPU,
    # ARMv7E-M ISA.  Architecture string is "CORTEX-M7" verbatim in ATDF.
    if "cortex-m7" in a_lower:
        return {"isa": "armv7e-m", "name": "cortex-m7f", "bits": 32, "fpu": True, "mpu": True}
    # Cortex-M4 — SAM4S, SAM4E, SAM4N, SAMG (M4F variants), SAMD51, SAME51.
    if a_lower.startswith("armv7") or "cortex-m4" in a_lower:
        return {"isa": "armv7e-m", "name": "cortex-m4f", "bits": 32, "fpu": True, "mpu": True}
    # Cortex-M3 — SAM3 line.
    if "cortex-m3" in a_lower:
        return {"isa": "armv7-m", "name": "cortex-m3", "bits": 32, "mpu": True}
    if a_lower.startswith("armv6") or "cortex-m0" in a_lower:
        return {"isa": "armv6-m", "name": "cortex-m0", "bits": 32}
    return {"isa": a_lower or "unknown", "name": _attr(device, "name").lower(), "bits": 32}


def _detect_package(root: ET.Element) -> str | None:
    variant = root.find(".//variants/variant")
    if variant is None:
        return None
    pkg = _attr(variant, "package").lower() or None
    return pkg


def _extract_pinout(root: ET.Element) -> list[dict[str, Any]]:
    """Extract per-package pinout from the ATDF's ``<pinouts><pinout
    name="<package>"><pin pad="..." position="..."/></pinout></pinouts>``
    block.  Picks the pinout matching the variant's declared package
    (when ``<variant pinout="QFN32"/>``); falls back to the first
    <pinout> when no match.

    Returns a v2.1 pinout[] list ready to drop into the payload.
    """
    variant = root.find(".//variants/variant")
    desired_pinout = _attr(variant, "pinout") if variant is not None else ""

    chosen: ET.Element | None = None
    for pn in root.iter("pinout"):
        name = _attr(pn, "name")
        if not desired_pinout or name == desired_pinout:
            chosen = pn
            break
    if chosen is None:
        # No pinout block at all — emit a placeholder so the schema
        # is satisfied (downstream extractors can overwrite).
        return [{"signal": "RESET"}]

    out: list[dict[str, Any]] = []
    for pin in chosen.iter("pin"):
        pad = _attr(pin, "pad")
        position = _parse_int(_attr(pin, "position"))
        if not pad:
            continue
        row: dict[str, Any] = {"signal": pad}
        if position is not None and position >= 1:
            row["pin"] = position
        # Pin-constraint heuristics — same vocabulary as STM32.
        upper = pad.upper()
        constraints: list[str] = []
        if upper in {"VDD", "VDDIO", "VDDA", "AVDD"} or upper.startswith("VDD"):
            constraints.append("power")
        elif upper in {"GND", "AGND", "VSS"} or upper.startswith("GND"):
            constraints.append("power")
        elif upper == "UPDI":
            constraints.append("debug-default")
        elif upper in {"RESET", "NRESET"}:
            constraints.append("reset")
        if constraints:
            row["constraints"] = constraints
        out.append(row)
    return out or [{"signal": "RESET"}]


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    atdf_path: Path,
) -> dict[str, Any]:
    """Extract one device from a Microchip ATDF as a v2.1 primitive payload."""
    if not atdf_path.exists():
        raise FileNotFoundError(f"ATDF file not found: {atdf_path}")
    root = ET.parse(atdf_path).getroot()

    identity_block: dict[str, Any] = {
        "vendor": vendor,
        "family": family,
        "device": device,
        "core":   _detect_core(root),
    }
    package = _detect_package(root)
    if package:
        identity_block["package"] = package

    memory = _walk_memory(root)
    templates, peripherals, interrupts = _extract_modules_block(root)

    if not memory:
        # Schema requires at least one row.  Emit a placeholder.
        memory = [{
            "id": "flash", "base": "0x00000000", "size": "1B",
            "access": "rx", "role": "extractor-placeholder",
        }]

    # ATDF carries package pinout under ``<pinouts><pinout name="X">
    # <pin pad="..." position="..."/></pinout></pinouts>``.  We pick
    # the pinout that matches the variant's declared package.
    pinout: list[dict[str, Any]] = _extract_pinout(root)

    payload: dict[str, Any] = {
        "schema":     "alloy.device.v2.1",
        "identity":   identity_block,
        "provenance": {
            "primary":  f"microchip-atdf:{atdf_path.name}",
            "authored": "auto",
            "notes":    "ATDF-extracted skeleton — pinout requires enrichment.",
        },
        "memory":     memory,
        "clock": {
            "oscillators": {
                "osc_int_8mhz":   {"freq": "8MHz",  "kind": "rc-internal"},
                "osc_int_128khz": {"freq": "128kHz", "kind": "rc-internal"},
                "osc_ext":        {"freq": "0Hz",   "kind": "crystal-external", "optional": True},
            },
            "domains": [
                {"id": "sysclk",
                 "sources": ["osc_int_8mhz", "osc_int_128khz", "osc_ext"]},
            ],
        },
    }
    if templates:
        payload["templates"] = templates
    payload["peripherals"] = peripherals
    payload["pinout"]      = pinout
    if interrupts:
        payload["interrupts"] = interrupts
    return payload


__all__ = ["extract_device"]
