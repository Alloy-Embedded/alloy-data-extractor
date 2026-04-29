"""TI MSP430 extractor — `add-msp430-extractor` (Phase 3.3).

Reads MSP430 vendor header files (the canonical
``msp430xxxx.h`` / ``msp430.h`` chain shipped with msp430-gcc /
TI Code Composer Studio) and projects them into canonical-IR-
shaped payloads.

MSP430 SFR layout is exposed via a flat block of preprocessor
``#define`` directives:

```c
#define DCOCTL_              0x0056    /* DCO Frequency Control */
#define DCOCTL              (HWREG8(DCOCTL_))
#define BCSCTL1_            0x0057    /* Basic Clock System Control 1 */
#define BCSCTL1             (HWREG8(BCSCTL1_))
#define P1IN_               0x0020
#define P1IN                (HWREG8(P1IN_))
sfrb(P1IN,    P1IN_);
sfrw(WDTCTL,  WDTCTL_);
sfrw_(TAR,    0x0170);
```

The extractor reads address-of-register defines
(``<NAME>_ = 0x...``) for the inventory and pairs them with
``sfrb``/``sfrw`` / ``sfrb_``/``sfrw_`` declarations to infer
register width (8-bit vs 16-bit).  When no explicit width
declaration is present, a conservative name-pattern fallback
catches the well-known 16-bit families (timer, watchdog, ADC).

Pin extraction (Phase 2.2): each ``PxIN`` register contributes
8 pins ``Px.0..Px.7``; ``PxSEL`` / ``PxSEL2`` / ``PxSEL0`` /
``PxSEL1`` registers determine the mux arity (1-bit single
selector vs 2-bit MSP430F2/G2/FR pair).  AF→peripheral mapping
itself is datasheet-only and stays out of scope for now — the
projected ``pins`` carry an empty ``alternate_functions`` list
and a ``mux_select_bits`` hint for downstream consumers.

`identity.core: msp430` is set explicitly.  No schema bump is
required (core is a free-form string).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)

MSP430_FAMILIES = ("msp430",)


# Match `#define NAME_ 0x0020` where the trailing underscore
# distinguishes the address constant from the dereferenced macro.
_DEFINE_PATTERN = re.compile(
    r"""\#define \s+
        (?P<name>[A-Z][A-Z0-9_]*?)_   # name with trailing _
        \s+
        \(? 0x(?P<addr>[0-9a-fA-F]+) \)?
        \s* (?:/\* .*? \*/)?
    """,
    re.VERBOSE | re.IGNORECASE,
)


# `sfrb(NAME, ...)` / `sfrw(NAME, ...)` / `sfrb_(NAME, ...)` /
# `sfrw_(NAME, ...)` declarations carry width information.
_SFR_DECL_PATTERN = re.compile(
    r"""\bsfr
        (?P<width>[bw])     # b → 8-bit, w → 16-bit
        _?                  # _ allowed for sfrb_ / sfrw_ forms
        \s*\(
        \s*(?P<name>[A-Z_][A-Z0-9_]*)
    """,
    re.VERBOSE | re.IGNORECASE,
)


# Fallback name-pattern recognition for chips that omit explicit
# sfrb/sfrw declarations.  Conservative: only mark register names
# that match a well-known 16-bit family.
_KNOWN_16BIT_NAME_PATTERNS = (
    re.compile(r"^WDTCTL$"),
    # Timer A: TAR / TACTL / TACCRn / TACCTLn / TAEX / TAIV
    # (and the indexed forms TA0R, TA1R …).
    re.compile(r"^TA[0-9]?(R|CTL|EX0?|IV)$"),
    re.compile(r"^TA[0-9]?CCR[0-9]+$"),
    re.compile(r"^TA[0-9]?CCTL[0-9]+$"),
    # Timer B: same shape as Timer A, B prefix.
    re.compile(r"^TB[0-9]?(R|CTL|EX0?|IV)$"),
    re.compile(r"^TB[0-9]?CCR[0-9]+$"),
    re.compile(r"^TB[0-9]?CCTL[0-9]+$"),
    # ADC10/ADC12 control + memory registers.
    re.compile(r"^ADC1[02](CTL[0-9]|MCTL[0-9]+|MEM[0-9]+|HI|LO|IFG|IV|IE)$"),
    # USCI 16-bit-wide registers (UCAxBRW, UCAxMCTLW on FRxx).
    re.compile(r"^UC[AB][0-9]+(BRW|MCTLW|STATW|RXBUFW|TXBUFW)$"),
    # Multiplier (16x16) high-word registers.
    re.compile(r"^MPY32(L|H|HH)?$"),
    re.compile(r"^RES(LO|HI)$"),
    # Reference / ADC start-conversion 16-bit on FRAM parts.
    re.compile(r"^REFCTL[0-9]?$"),
)


_PERIPHERAL_RE = re.compile(r"^([A-Za-z]+?)(\d+)?$")


@dataclass(frozen=True, slots=True)
class Msp430Register:
    """One MSP430 register address constant."""

    name: str
    address: int
    width_bits: int = 8


def _infer_widths(text: str) -> dict[str, int]:
    """Build a name→width map from explicit ``sfrb``/``sfrw``
    declarations.  Falls back silently when both forms appear for
    the same name (unlikely but harmless: 16-bit wins)."""
    widths: dict[str, int] = {}
    for match in _SFR_DECL_PATTERN.finditer(text):
        name = match.group("name")
        width = 16 if match.group("width").lower() == "w" else 8
        # Promote to 16-bit if any declaration says so — protects
        # against edge-case headers that ship both `sfrb(NAME, ...)`
        # and `sfrw(NAME, ...)` (the 16-bit form is correct in TI's
        # newer headers; the legacy 8-bit form is a compatibility
        # alias).
        widths[name] = max(widths.get(name, 0), width)
    return widths


def _matches_known_16bit_pattern(name: str) -> bool:
    return any(p.match(name) for p in _KNOWN_16BIT_NAME_PATTERNS)


def parse_msp430_header(text: str) -> tuple[Msp430Register, ...]:
    """Parse an MSP430 vendor header into typed register rows.

    Width inference (Phase 2.1):

    * ``sfrb`` / ``sfrw`` declarations are authoritative.
    * Otherwise, a conservative name-pattern fallback marks
      well-known 16-bit registers (timer / WDT / ADC / multiplier).
    * Default width is 8 bits.
    """
    declared_widths = _infer_widths(text)

    seen: set[str] = set()
    out: list[Msp430Register] = []
    for match in _DEFINE_PATTERN.finditer(text):
        name = match.group("name")
        if name in seen:
            continue
        seen.add(name)
        addr = int(match.group("addr"), 16)
        if name in declared_widths:
            width = declared_widths[name]
        elif _matches_known_16bit_pattern(name):
            width = 16
        else:
            width = 8
        out.append(Msp430Register(name=name, address=addr, width_bits=width))
    out.sort(key=lambda r: (r.address, r.name))
    return tuple(out)


_PORT_REGISTER_RE = re.compile(
    r"^(P\d+)(IN|OUT|DIR|REN|SEL[012]?|IE|IES|IFG|DS)$"
)


def _peripheral_group(register_name: str) -> str:
    """Strip trailing instance digits.  ``UCA0CTL`` keeps the
    ``UCA0`` prefix; ``P1IN`` becomes ``P1`` (port group)."""
    # First try classical PORT-style: P1IN → P1.
    port_match = _PORT_REGISTER_RE.match(register_name)
    if port_match:
        return port_match.group(1)
    # USCI: UCA0CTL0 → UCA0.
    usci_match = re.match(r"^(UC[AB]\d+)", register_name)
    if usci_match:
        return usci_match.group(1)
    # Generic fallback: NAME12CTL → NAME12.
    generic = _PERIPHERAL_RE.match(register_name)
    if generic and generic.group(2):
        return f"{generic.group(1)}{generic.group(2)}"
    # No instance suffix; use a CPU-bucket hint.
    return "CPU"


@dataclass(frozen=True, slots=True)
class Msp430PinPort:
    """One GPIO port discovered from ``PxIN``/``PxSEL*`` registers."""

    name: str
    in_address: int
    pin_count: int
    mux_select_bits: int


def _discover_pin_ports(
    registers: tuple[Msp430Register, ...],
) -> tuple[Msp430PinPort, ...]:
    """Group port-style registers (``PxIN``/``PxSEL`` etc.) into one
    :class:`Msp430PinPort` per ``Px`` prefix.

    Mux arity rules (``mux_select_bits``):

    * Two SEL registers (``PxSEL`` + ``PxSEL2``) or
      (``PxSEL0`` + ``PxSEL1``) → 2 bits → 4 alternate functions
      per pin.
    * One SEL register (``PxSEL`` only) → 1 bit → 2 alternate
      functions per pin.
    * No SEL register → 0 bits → port pins are GPIO-only.

    The pin count defaults to 8 (MSP430 ports are 8-bit) but
    falls back to 0 when the port has no IN register.
    """
    by_port: dict[str, dict[str, Msp430Register]] = {}
    for reg in registers:
        match = _PORT_REGISTER_RE.match(reg.name)
        if not match:
            continue
        port = match.group(1)
        suffix = match.group(2)
        by_port.setdefault(port, {})[suffix] = reg

    out: list[Msp430PinPort] = []
    for port_name in sorted(by_port):
        regs = by_port[port_name]
        in_reg = regs.get("IN")
        if in_reg is None:
            continue  # bare PxSEL on its own doesn't count as a port.
        sel_set = {key for key in regs if key.startswith("SEL")}
        if {"SEL", "SEL2"}.issubset(sel_set) or {"SEL0", "SEL1"}.issubset(sel_set):
            mux_bits = 2
        elif sel_set:
            mux_bits = 1
        else:
            mux_bits = 0
        out.append(
            Msp430PinPort(
                name=port_name,
                in_address=in_reg.address,
                pin_count=8,
                mux_select_bits=mux_bits,
            )
        )
    return tuple(out)


def _project_pins(ports: tuple[Msp430PinPort, ...]) -> list[dict[str, Any]]:
    """Expand GPIO ports into one canonical-IR pin entry per pin."""
    pins: list[dict[str, Any]] = []
    for port in ports:
        for bit in range(port.pin_count):
            pins.append(
                {
                    "name": f"{port.name}.{bit}",
                    "port": port.name,
                    "bit": bit,
                    "mux_select_bits": port.mux_select_bits,
                    # AF tables aren't in MSP430 headers — datasheet
                    # enrichment is a downstream concern (Phase 2.2
                    # docstring).  We surface an empty list so the
                    # canonical schema stays consistent.
                    "alternate_functions": [],
                }
            )
    return pins


def _project_to_payload(
    *,
    vendor: str,
    family: str,
    device: str,
    registers: tuple[Msp430Register, ...],
    pin_ports: tuple[Msp430PinPort, ...],
    source_path: Path,
    revision: str,
) -> dict[str, Any]:
    by_peripheral: dict[str, list[Msp430Register]] = {}
    for reg in registers:
        by_peripheral.setdefault(_peripheral_group(reg.name), []).append(reg)

    peripherals: list[dict[str, Any]] = []
    for name, group in sorted(by_peripheral.items()):
        peripherals.append(
            {
                "name": name,
                "base_address": min(r.address for r in group),
                "kind": "msp430-sfr-group",
            }
        )

    register_rows = [
        {
            "name": r.name,
            "address": r.address,
            "width_bits": r.width_bits,
        }
        for r in registers
    ]

    return {
        "schema_version": "1.3.0",
        "identity": {
            "vendor": vendor,
            "family": family,
            "device": device,
            "package": "",
            "core": "msp430",
            "summary": f"Admitted via MSP430 vendor header ({source_path.name}).",
        },
        "provenance": {
            "source_id": "msp430",
            "source_path": str(source_path),
            "patch_ids": [f"msp430-header@{revision}"],
        },
        "memories": [],
        "peripherals": peripherals,
        "registers": register_rows,
        "pins": _project_pins(pin_ports),
    }


def _resolve_header(request: ExtractionRequest) -> Path | None:
    for key in ("msp430", "msp430-header"):
        if key in request.source_paths:
            return request.source_paths[key]
    return None


@register_extractor(
    "msp430",
    families=tuple(("ti", fam) for fam in MSP430_FAMILIES),
)
class Msp430Extractor:
    """TI MSP430 extractor — Phase 3.3 implementation."""

    extractor_id: str = "msp430"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        header_path = _resolve_header(request)
        if header_path is None or not header_path.exists():
            available = sorted(request.source_paths)
            raise ValueError(
                f"msp430 extractor: cannot resolve vendor header for "
                f"{request.device}.  Pass --source msp430=<header> "
                f"or --source msp430-header=<header>.  "
                f"Got source keys: {available}"
            )
        text = header_path.read_text(encoding="utf-8", errors="replace")
        registers = parse_msp430_header(text)
        pin_ports = _discover_pin_ports(registers)
        payload = _project_to_payload(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            registers=registers,
            pin_ports=pin_ports,
            source_path=header_path,
            revision=request.revision,
        )
        warnings: list[str] = []
        if not any(r.width_bits == 16 for r in registers):
            warnings.append(
                "MSP430 extractor: no 16-bit registers detected — "
                "verify the header carries `sfrw` declarations or "
                "TI-style 16-bit register names."
            )
        if not pin_ports:
            warnings.append(
                "MSP430 extractor: no GPIO ports discovered — "
                "header lacks PxIN registers."
            )
        # AF→peripheral mapping is datasheet-only.
        warnings.append(
            "MSP430 extractor: AF→peripheral mapping is "
            "datasheet-only and stays out of scope; pins[*]."
            "alternate_functions is intentionally empty.",
        )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="msp430",
                source_path=str(header_path),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = [
    "MSP430_FAMILIES",
    "Msp430Extractor",
    "Msp430PinPort",
    "Msp430Register",
    "parse_msp430_header",
]
