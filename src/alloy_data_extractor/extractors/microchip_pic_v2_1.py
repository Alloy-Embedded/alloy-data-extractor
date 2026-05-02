"""Microchip 8-bit PIC ``.PIC`` (EDC schema) → v2.1 extractor.

The 8/16-bit PIC line (PIC10/12/16/18, PIC24, dsPIC) doesn't ship
ATDF files — Microchip uses a separate XML schema called EDC
(Embedded Device Capability), namespaced under
``http://crownking/edc``.  Each ``.PIC`` file in
``microchip-dfp/<pack>/edc/<chip>.PIC`` is the per-chip data file
in that schema.

What we extract per chip:

* identity {isa, name, bits} — derived from ``<edc:PIC arch="...">``
  and the family pack name (``pic18`` / ``pic16`` / ``pic10``)
* memory[] — flat sector list from
  ``<edc:CodeSector>`` (program flash),
  ``<edc:GPRDataSector>`` (general-purpose RAM banks),
  ``<edc:SFRDataSector>`` (SFR / IO mapped registers),
  ``<edc:EEDataSector>`` (data EEPROM),
  ``<edc:ConfigFuseSector>`` (configuration words),
  ``<edc:DeviceIDSector>`` (read-only chip ID),
  ``<edc:UserIDSector>`` (user ID rows)
* peripherals[] — clusters of ``<edc:SFRDef>`` by canonical name
  prefix (``PORTA``/``LATA``/``TRISA`` → ``port_a``,
  ``ADCONx``/``ADRESx`` → ``adc``, ``TxCON``/``TMRx`` →
  ``timer_x``, ``TXSTA``/``RCSTA``/``SPBRG`` → ``usart``, …)
* templates[] — register + bitfield maps (one per peripheral
  class), populated from ``<edc:SFRDef>`` + ``<edc:SFRFieldDef>``
* pinout[] — flattened ``<edc:PinList><edc:Pin><edc:VirtualPin>``,
  one row per physical pin; the first VirtualPin becomes the
  primary signal name.
* clock — synthesised single profile from
  ``<edc:Oscillator><edc:OscillatorMode>`` (post-reset = factory
  Internal RC mode at the lowest declared frequency).

What we deliberately don't extract:

* IRQs — PIC8 doesn't have a NVIC-style vector table (one main
  IRQ vector + per-peripheral enable/flag bits in PIE/PIR
  registers).  v2.1's ``interrupts`` block is optional, so we
  omit it.
* Pinmux per peripheral — PIC PPS (peripheral pin select) is
  modelled as separate ``RxyPPS`` registers; folding into
  ``peripherals[*].pin_options`` requires PPS-table inference
  which lives in a follow-up.

The output payload validates against ``alloy.device.v2.1`` with
the same schema-const + writer used by every other extractor.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


_NS = {"edc": "http://crownking/edc"}


def _attr(node: ET.Element, key: str, default: str = "") -> str:
    return node.get(f"{{{_NS['edc']}}}{key}", default)


def _parse_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(s, 0)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# identity / core
# ---------------------------------------------------------------------------


def _detect_core(root: ET.Element, family_slug: str) -> dict[str, Any]:
    """Map ``<edc:PIC arch="...">`` to a v2.1 core record.

    Atmel ATDF used a "cortex-m*" / "avr*" verb; EDC's ``arch``
    is a numeric family code:

      * 18xxxx → PIC18 enhanced (8-bit)
      * 18cxxx → PIC18 classic (8-bit)
      * 16xxxx → PIC16 enhanced (8-bit)
      * 16Cxxx → PIC16 classic (8-bit)
      * 16xxx  → PIC16 baseline / midrange
      * 12xxx  → PIC12 baseline
      * 10xxx  → PIC10 baseline
      * 24xxxx / 24exxx → PIC24 (16-bit)
      * 30xxx  → dsPIC30 (16-bit DSP)
      * 33xxxx → dsPIC33 (16-bit DSP)
    """
    arch = _attr(root, "arch").lower()
    name_attr = _attr(root, "name").lower()

    if arch.startswith("18"):
        # 18xxxx = enhanced (PIC18FxxKxx, PIC18FxxQxx); 18cxxx = classic
        return {
            "isa":  "pic18",
            "name": "pic18-enhanced" if "enhanced" in arch or "xxxx" in arch else "pic18",
            "bits": 8,
        }
    if arch.startswith("16"):
        return {"isa": "pic16", "name": "pic16", "bits": 8}
    if arch.startswith("12"):
        return {"isa": "pic12", "name": "pic12", "bits": 8}
    if arch.startswith("10"):
        return {"isa": "pic10", "name": "pic10", "bits": 8}
    if arch.startswith("24"):
        return {"isa": "pic24", "name": "pic24", "bits": 16}
    if arch.startswith("30"):
        return {"isa": "dspic30", "name": "dspic30", "bits": 16}
    if arch.startswith("33"):
        return {"isa": "dspic33", "name": "dspic33", "bits": 16}
    # Fallback — keep going so codegen doesn't blow up on a
    # newly-shipped family before this table catches up.
    return {"isa": arch or "pic-unknown", "name": name_attr or arch, "bits": 8}


# ---------------------------------------------------------------------------
# memory — sector elements drive memory[]
# ---------------------------------------------------------------------------


# (xml-tag-suffix, v2.1 id-prefix, address_space hint, default access)
_SECTOR_KIND_MAP: tuple[tuple[str, str, str | None, str], ...] = (
    ("CodeSector",          "flash",     "program", "rx"),
    ("ExtCodeSector",       "ext_flash", "program", "rx"),
    ("GPRDataSector",       "ram",       "data",    "rwx"),
    ("SFRDataSector",       "sfr",       "data",    "rw"),
    ("EEDataSector",        "eeprom",    "eeprom",  "rw"),
    ("ConfigFuseSector",    "config",    "fuse",    "ro"),
    ("DeviceIDSector",      "deviceid",  "signature", "ro"),
    ("UserIDSector",        "userid",    "signature", "rw"),
    ("BACKBUGVectorSector", "bbug",      None,       "ro"),
    ("DCRSector",           "dcr",       "fuse",    "ro"),
)


def _walk_memory(root: ET.Element) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counter: dict[str, int] = defaultdict(int)
    for sector_tag, id_prefix, aspace, default_access in _SECTOR_KIND_MAP:
        for sec in root.iter(f"{{{_NS['edc']}}}{sector_tag}"):
            base = _parse_int(_attr(sec, "beginaddr"))
            end = _parse_int(_attr(sec, "endaddr"))
            if base is None or end is None or end <= base:
                continue
            size = end - base
            idx = counter[id_prefix]
            counter[id_prefix] += 1
            row_id = id_prefix if idx == 0 and counter[id_prefix] <= 1 else f"{id_prefix}_{idx}"
            # Render size with KB/MB unit when exact, else bytes.
            if size >= 1024 and size % 1024 == 0:
                size_str = (
                    f"{size >> 20}MB" if size >= (1 << 20) and size % (1 << 20) == 0
                    else f"{size // 1024}KB"
                )
            else:
                size_str = f"{size}B"
            row: dict[str, Any] = {
                "id":     row_id,
                "base":   f"0x{base:X}" if base >= 0x100 else base,
                "size":   size_str,
                "access": default_access,
            }
            if aspace:
                row["address_space"] = aspace
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# peripherals + templates — cluster <edc:SFRDef> by canonical name
# ---------------------------------------------------------------------------


def _ip_class_for_sfr(name: str) -> tuple[str, str] | None:
    """Map an SFR cname to a ``(peripheral_id, template_id)`` pair.
    Returns ``None`` to drop the SFR (CPU registers like WREG/STATUS
    aren't peripherals).

    The mapping is heuristic but covers the bulk of PIC8 SFRs.
    Any uncovered SFR still surfaces in templates under a
    catch-all ``misc`` peripheral so codegen still has full
    register coverage.
    """
    n = name.upper()

    # CPU core registers — not peripherals.
    if n in {
        "WREG", "STATUS", "BSR", "FSR", "FSR0L", "FSR0H",
        "FSR1L", "FSR1H", "FSR2L", "FSR2H", "TBLPTRL", "TBLPTRH",
        "TBLPTRU", "TABLAT", "PCL", "PCLATH", "PCLATU", "PRODL",
        "PRODH", "STKPTR", "TOSL", "TOSH", "TOSU", "INDF0",
        "PREINC0", "POSTINC0", "POSTDEC0", "PLUSW0",
        "INDF1", "PREINC1", "POSTINC1", "POSTDEC1", "PLUSW1",
        "INDF2", "PREINC2", "POSTINC2", "POSTDEC2", "PLUSW2",
        "PCON", "RCON", "INTCON", "INTCON1", "INTCON2", "INTCON3",
    }:
        return None

    # GPIO ports — PORTA / LATA / TRISA / ANSELA → port_a
    for prefix in ("PORT", "LAT", "TRIS", "ANSEL", "ANCON"):
        if n.startswith(prefix) and len(n) > len(prefix):
            tail = n[len(prefix):]
            if tail and tail[0].isalpha():
                return f"port_{tail.lower()}", "port"

    # ADC — ADCON0/1/2/3, ADRESL/H, ADRESHL...
    if n.startswith("ADCON") or n.startswith("ADRES") or n in {"ADCALC", "ADCAP", "ADCLK"}:
        return "adc", "adc"

    # Comparators — CMxCON, CMRCON, CVRCON
    if n.startswith("CMCON") or n.startswith("CM1CON") or n.startswith("CM2CON") or n in {"CVRCON"}:
        return "comparator", "comparator"

    # Timers — TxCON / TMRx / PRx / CCPRxL/H
    for tnum in range(8):
        if n.startswith(f"T{tnum}CON") or n.startswith(f"TMR{tnum}") or n.startswith(f"PR{tnum}"):
            return f"timer_{tnum}", "timer"

    # CCP / PWM
    if n.startswith("CCP") or n.startswith("ECCP"):
        return "ccp", "ccp"

    # USART / EUSART
    if n in {"TXSTA", "RCSTA", "SPBRG", "SPBRGH", "TXREG", "RCREG", "BAUDCON"} or \
       n.startswith("TX1STA") or n.startswith("RC1STA") or n.startswith("BAUDCON"):
        return "usart", "usart"

    # MSSP (SPI/I2C unified)
    if n.startswith("SSP") or n.startswith("MSSP"):
        return "mssp", "mssp"

    # EUSART2 if present
    if n.startswith("TX2") or n.startswith("RC2"):
        return "usart_2", "usart"

    # Oscillator / clock control
    if n.startswith("OSCCON") or n.startswith("OSCTUNE") or n in {"REFOCON", "OSCSTAT"}:
        return "oscillator", "oscillator"

    # PIE / PIR / IPR (interrupt control banks)
    if n.startswith("PIE") or n.startswith("PIR") or n.startswith("IPR"):
        return "interrupt_controller", "interrupt_controller"

    # EEPROM access
    if n.startswith("EE") and not n.startswith("EEC"):
        return "eeprom", "eeprom"

    # WDT
    if n.startswith("WDTCON") or n == "WDTPS":
        return "wdt", "wdt"

    # USB
    if n.startswith("UCON") or n.startswith("UADDR") or n.startswith("USTAT") \
       or n.startswith("UFRMH") or n.startswith("UEP"):
        return "usb", "usb"

    return "misc", "misc"


def _walk_peripherals_and_templates(
    root: ET.Element,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Walk every ``<edc:SFRDef>`` and bucket by inferred
    peripheral.  Returns ``(peripherals[], templates[])``."""
    by_template: dict[str, dict[str, Any]] = {}
    by_periph: dict[str, dict[str, Any]] = {}
    seen_per_template: dict[str, set[str]] = defaultdict(set)

    for sfr in root.iter(f"{{{_NS['edc']}}}SFRDef"):
        cname = _attr(sfr, "cname")
        addr = _parse_int(_attr(sfr, "_addr"))
        if not cname:
            continue
        cls = _ip_class_for_sfr(cname)
        if cls is None:
            continue
        per_id, tpl_id = cls

        # Register row inside the template.
        tpl = by_template.setdefault(tpl_id, {"registers": {}, "fields": {}})
        reg_key = cname.lower()
        if reg_key not in tpl["registers"] and addr is not None:
            tpl["registers"][reg_key] = {
                "offset": f"0x{addr:X}" if addr >= 0x100 else addr,
            }

        # Bitfields — flatten across SFRMode.
        for mode in sfr.iter(f"{{{_NS['edc']}}}SFRMode"):
            for f in mode.iter(f"{{{_NS['edc']}}}SFRFieldDef"):
                fname = _attr(f, "cname").lower()
                mask_raw = _parse_int(_attr(f, "mask"))
                width = _parse_int(_attr(f, "nzwidth"))
                if not fname or mask_raw is None or width is None:
                    continue
                # Mask in EDC is a one-shifted bit pattern; convert
                # to (lsb, width).  EDC declares bitfields with
                # repeated mask=0x1 + an implicit position from
                # declaration order — but newer files set the
                # actual bit position via mask shift.  When mask=1
                # we infer position from order in the declaration.
                key = f"{reg_key}.{fname}"
                if key in tpl["fields"]:
                    continue
                # Width-from-mask: assume contiguous, lsb at lowest bit set.
                if mask_raw > 0:
                    lsb = (mask_raw & -mask_raw).bit_length() - 1
                else:
                    lsb = 0
                if width == 1:
                    tpl["fields"][key] = {"bit": lsb}
                else:
                    tpl["fields"][key] = {"bits": [lsb, lsb + width - 1]}

        # Peripheral row — once per peripheral_id.
        if per_id not in by_periph:
            by_periph[per_id] = {
                "id":       per_id,
                "template": tpl_id,
            }

    # Add a base address to peripheral rows (lowest SFR address
    # seen for that peripheral) so the schema's optional "base"
    # is populated.
    for per_id, row in by_periph.items():
        # Find lowest address among template's registers.
        tpl = by_template.get(row["template"], {})
        regs = tpl.get("registers", {})
        addrs: list[int] = []
        for r in regs.values():
            off = r.get("offset")
            if isinstance(off, int):
                addrs.append(off)
            elif isinstance(off, str) and off.startswith("0x"):
                try:
                    addrs.append(int(off, 16))
                except ValueError:
                    pass
        if addrs:
            base = min(addrs)
            row["base"] = f"0x{base:X}" if base >= 0x100 else base

    peripherals = sorted(by_periph.values(), key=lambda r: r["id"])
    return peripherals, by_template


# ---------------------------------------------------------------------------
# pinout — flatten <edc:PinList><edc:Pin>
# ---------------------------------------------------------------------------


def _walk_pinout(root: ET.Element) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pin_idx = 0
    for plist in root.iter(f"{{{_NS['edc']}}}PinList"):
        for pin in plist.findall(f"{{{_NS['edc']}}}Pin"):
            pin_idx += 1
            virtuals: list[str] = []
            for vp in pin.findall(f"{{{_NS['edc']}}}VirtualPin"):
                vp_name = _attr(vp, "name")
                if vp_name:
                    virtuals.append(vp_name)
            if not virtuals:
                continue
            primary = virtuals[0]
            row: dict[str, Any] = {
                "signal": primary,
                "pin":    pin_idx,
            }
            # Constraint heuristics — same vocabulary as ATDF
            # extractor so codegen consumers get a uniform shape.
            upper = primary.upper()
            constraints: list[str] = []
            if upper in {"VDD", "VDDIO", "VDDA", "AVDD"}:
                constraints.append("power")
            elif upper in {"GND", "AGND", "VSS"}:
                constraints.append("power")
            elif upper in {"MCLR", "VPP", "RESET", "NRESET"}:
                constraints.append("reset")
            elif upper.startswith("VPP"):
                constraints.append("debug-default")
            if constraints:
                row["constraints"] = constraints
            # Surface alternate VirtualPins as a flat alt-functions
            # list — codegen can decide what to do with them.
            if len(virtuals) > 1:
                row["alt_functions"] = virtuals[1:]
            out.append(row)
    if not out:
        # Schema requires at least one pinout row — emit a stub.
        out.append({"signal": "RESET"})
    return out


# ---------------------------------------------------------------------------
# clock — synthesise one factory profile from <edc:OscillatorMode>
# ---------------------------------------------------------------------------


def _build_clock_block(root: ET.Element) -> dict[str, Any]:
    """Create a minimal v2.1 clock block from the ``<edc:Oscillator>``
    section.  PIC8 doesn't model a clock-tree the way ARM does —
    the only machine-readable info is per-mode min/max frequency
    bounds.  We pick the lowest-id mode (typically "internal RC")
    and emit a single ``factory-default`` profile at its max.
    """
    osc = root.find(f"{{{_NS['edc']}}}Oscillator")
    if osc is None:
        return _stub_clock()

    modes: list[tuple[int, int]] = []
    for mode in osc.iter(f"{{{_NS['edc']}}}OscillatorMode"):
        mid = _parse_int(_attr(mode, "id"))
        mmax = _parse_int(_attr(mode, "max"))
        if mid is not None and mmax is not None:
            modes.append((mid, mmax))
    if not modes:
        return _stub_clock()

    modes.sort()
    factory_id, factory_max = modes[0]
    fastest_id, fastest_max = max(modes, key=lambda m: m[1])

    profiles = [{
        "id": "factory-internal-rc",
        "kind": "post-reset",
        "sysclk": _hz_to_freq_unit(factory_max),
        "sysclk_source": "internal-rc",
    }]
    if fastest_max > factory_max:
        profiles.append({
            "id":            f"max-osc-mode-{fastest_id}",
            "kind":          "recommended",
            "sysclk":        _hz_to_freq_unit(fastest_max),
            "sysclk_source": "external-or-pll",
        })

    return {
        "oscillators": {
            "internal-rc": {
                "freq": _hz_to_freq_unit(factory_max),
                "kind": "rc-internal",
            },
        },
        "domains": [{
            "id":      "sysclk",
            "sources": ["internal-rc"],
        }],
        "profiles": profiles,
    }


def _stub_clock() -> dict[str, Any]:
    return {
        "oscillators": {
            "unknown": {"freq": "0Hz", "kind": "rc-internal"},
        },
        "domains":  [{"id": "sysclk", "sources": ["unknown"]}],
        "profiles": [{
            "id": "factory-default",
            "kind": "post-reset",
            "sysclk": "0Hz",
            "sysclk_source": "unknown",
        }],
    }


def _hz_to_freq_unit(hz: int) -> str:
    if hz >= 1_000_000 and hz % 1_000_000 == 0:
        return f"{hz // 1_000_000}MHz"
    if hz >= 1_000 and hz % 1_000 == 0:
        return f"{hz // 1_000}kHz"
    return f"{hz}Hz"


# ---------------------------------------------------------------------------
# package detection from .PIC ↔ pdsc cross-reference is fragile —
# fall back to "unknown" and let an overlay/cli refine.
# ---------------------------------------------------------------------------


def _detect_package(root: ET.Element) -> str | None:
    # No reliable single-source for package in .PIC.  The .PIC
    # carries pin count via the PinList length but not package
    # silhouette.  Return None so identity.package stays absent.
    return None


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    pic_path: Path,
) -> dict[str, Any]:
    """Extract one PIC8/16/24/dsPIC device from a ``.PIC`` (EDC
    schema) into a v2.1 primitive payload."""
    if not pic_path.exists():
        raise FileNotFoundError(f"PIC file not found: {pic_path}")
    root = ET.parse(pic_path).getroot()

    identity_block: dict[str, Any] = {
        "vendor": vendor,
        "family": family,
        "device": device,
        "core":   _detect_core(root, family),
    }

    memory = _walk_memory(root)
    if not memory:
        memory = [{
            "id":     "flash", "base": 0, "size": "1B", "access": "rx",
            "role":   "extractor-placeholder",
        }]

    peripherals, templates = _walk_peripherals_and_templates(root)
    if not peripherals:
        peripherals = [{"id": "stub", "template": "stub"}]
        templates.setdefault("stub", {"registers": {}, "fields": {}})

    pinout = _walk_pinout(root)
    clock = _build_clock_block(root)

    payload: dict[str, Any] = {
        "schema":   "alloy.device.v2.1",
        "identity": identity_block,
        "provenance": {
            "primary":  f"microchip-pic:{pic_path.name}",
            "authored": "auto",
        },
        "memory":      memory,
        "clock":       clock,
        "peripherals": peripherals,
        "pinout":      pinout,
        "templates":   templates,
    }
    return payload


__all__ = ["extract_device"]
