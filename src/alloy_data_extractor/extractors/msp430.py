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
```

We extract the address-of-register defines (``<NAME>_`` =
``0x...``) and project each as one register row, grouped by
peripheral prefix.

`identity.core: msp430` is set explicitly.  No schema bump is
required (core is a free-form string).

Vendor-specific extensions (peripheral-bus / register-bank
indirection, port-multiplexing) are deferred — this v1 covers
the basic register inventory.
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


_PERIPHERAL_RE = re.compile(r"^([A-Za-z]+?)(\d+)?$")


@dataclass(frozen=True, slots=True)
class Msp430Register:
    """One MSP430 register address constant."""

    name: str
    address: int
    width_bits: int = 8  # MSP430 default; we don't infer 16-bit yet


def parse_msp430_header(text: str) -> tuple[Msp430Register, ...]:
    """Parse an MSP430 vendor header into typed register rows."""
    seen: set[str] = set()
    out: list[Msp430Register] = []
    for match in _DEFINE_PATTERN.finditer(text):
        name = match.group("name")
        if name in seen:
            continue
        seen.add(name)
        addr = int(match.group("addr"), 16)
        out.append(Msp430Register(name=name, address=addr))
    out.sort(key=lambda r: (r.address, r.name))
    return tuple(out)


def _peripheral_group(register_name: str) -> str:
    """Strip trailing instance digits.  ``UCA0CTL`` keeps the
    ``UCA0`` prefix; ``P1IN`` becomes ``P1`` (port group)."""
    # First try classical PORT-style: P1IN → P1.
    port_match = re.match(r"^(P\d+)(?:IN|OUT|DIR|REN|SEL\d?|IE|IES|IFG)$", register_name)
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


def _project_to_payload(
    *,
    vendor: str,
    family: str,
    device: str,
    registers: tuple[Msp430Register, ...],
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
        payload = _project_to_payload(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            registers=registers,
            source_path=header_path,
            revision=request.revision,
        )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="msp430",
                source_path=str(header_path),
                revision=request.revision,
            ),
            warnings=(
                "MSP430 extractor: peripheral-bus indirection + "
                "port-multiplexing tables not yet emitted — "
                "Phase 3.3 follow-up.",
            ),
        )


__all__ = [
    "MSP430_FAMILIES",
    "Msp430Extractor",
    "Msp430Register",
    "parse_msp430_header",
]
