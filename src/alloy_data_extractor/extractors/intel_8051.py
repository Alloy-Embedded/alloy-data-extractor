"""8051-derivative extractor — `add-8051-extractor` (Phase 4.2).

Reads SDCC-flavored 8051 SFR headers and projects them as
canonical-IR-shaped payloads.

The 8051 SFR header format is well-defined and shared across
Nuvoton N76, SiLabs EFM8, STC15W, and most modern 8051
derivatives.  Each Special-Function Register (SFR) is declared
inline:

```c
__sfr __at (0x80) P0;
__sfr __at (0x81) SP;
__sbit __at (0x80) P0_0;
sfr16 __at (0x82) DPTR;
```

This v1 implementation handles ``__sfr __at (...)``,
``sfr16 __at (...)``, and ``__sbit __at (...)`` declarations —
the most common forms.  Vendor-specific extensions (banking,
indirect addressing) are deferred.

Output shape:

* `peripherals`: each SFR group (SFR name prefix → distinct
  peripheral) becomes one peripheral row at its lowest SFR
  address.
* `registers`: each SFR becomes one register row.

Identity.core is hard-coded to ``i8051`` for the family — the
schema accepts string values, so no schema bump is required.
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

_8051_FAMILIES: tuple[tuple[str, str], ...] = (
    ("nuvoton", "n76"),
    ("nuvoton", "n79"),
    ("silabs", "efm8"),
    ("stc", "stc15w"),
)


# Match `__sfr __at (0x80) NAME;` and `sfr __at (0x80) NAME;`
# (some vendors use the ANSI form, some the SDCC form).
_SFR_PATTERN = re.compile(
    r"""(?:__)?sfr (?:16)?           # __sfr / sfr / sfr16
        \s+ (?:__)?at \s* \(?\s*    # __at(  /  at  / __at
        (?P<addr>0x[0-9a-fA-F]+)    # the address literal
        \s*\)?\s*                   # closing )
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        \s* ;""",
    re.VERBOSE,
)

_SBIT_PATTERN = re.compile(
    r"""(?:__)?sbit
        \s+ (?:__)?at \s* \(?\s*
        (?P<addr>0x[0-9a-fA-F]+)
        \s*\)?\s*
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        \s* ;""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class Sfr:
    """One Special-Function Register."""

    name: str
    address: int
    is_bit: bool = False
    width_bits: int = 8


def parse_sfr_header(text: str) -> tuple[Sfr, ...]:
    """Parse an 8051 SFR header into typed Sfr rows."""
    sfrs: list[Sfr] = []
    seen: set[tuple[str, int]] = set()
    for match in _SFR_PATTERN.finditer(text):
        addr = int(match.group("addr"), 16)
        name = match.group("name")
        # Distinguish 16-bit SFRs (sfr16) from 8-bit by the literal.
        width = 16 if match.group(0).strip().startswith(("sfr16", "__sfr16")) else 8
        if "sfr16" in match.group(0):
            width = 16
        key = (name, addr)
        if key in seen:
            continue
        seen.add(key)
        sfrs.append(Sfr(name=name, address=addr, width_bits=width))
    for match in _SBIT_PATTERN.finditer(text):
        addr = int(match.group("addr"), 16)
        name = match.group("name")
        key = (name, addr)
        if key in seen:
            continue
        seen.add(key)
        sfrs.append(Sfr(name=name, address=addr, is_bit=True, width_bits=1))
    return tuple(sorted(sfrs, key=lambda s: (s.address, s.name)))


_PERIPHERAL_PREFIX_RE = re.compile(r"^([A-Za-z]+?)(\d+|_\d+)?(?:_[A-Z0-9]+)?$")


def _peripheral_group(sfr_name: str) -> str:
    """Heuristic: ``UART0_TX`` → ``UART0``; ``P0_0`` → ``P0``;
    fall back to the SFR name itself."""
    match = _PERIPHERAL_PREFIX_RE.match(sfr_name)
    if not match:
        return sfr_name
    prefix = match.group(1)
    suffix = match.group(2) or ""
    if suffix.startswith("_"):
        suffix = suffix[1:]
    return f"{prefix}{suffix}"


def _project_to_payload(
    *,
    vendor: str,
    family: str,
    device: str,
    sfrs: tuple[Sfr, ...],
    source_path: Path,
    revision: str,
) -> dict[str, Any]:
    # Group SFRs by peripheral → peripheral row at lowest address.
    by_peripheral: dict[str, list[Sfr]] = {}
    for sfr in sfrs:
        if sfr.is_bit:
            continue
        group = _peripheral_group(sfr.name)
        by_peripheral.setdefault(group, []).append(sfr)

    peripherals: list[dict[str, Any]] = []
    for group_name, group_sfrs in sorted(by_peripheral.items()):
        peripherals.append(
            {
                "name": group_name,
                "base_address": min(s.address for s in group_sfrs),
                "kind": "sfr-group",
            }
        )

    registers = [
        {
            "name": s.name,
            "address": s.address,
            "width_bits": s.width_bits,
            "is_bit": s.is_bit,
        }
        for s in sfrs
    ]

    return {
        "schema_version": "1.3.0",
        "identity": {
            "vendor": vendor,
            "family": family,
            "device": device,
            "package": "",
            "core": "i8051",
            "summary": f"Admitted via 8051 SFR header ({source_path.name}).",
        },
        "provenance": {
            "source_id": "intel-8051",
            "source_path": str(source_path),
            "patch_ids": [f"sfr-header@{revision}"],
        },
        "memories": [],
        "peripherals": peripherals,
        "registers": registers,
    }


def _resolve_header(request: ExtractionRequest) -> Path | None:
    for key in ("intel-8051", "sfr-header"):
        if key in request.source_paths:
            return request.source_paths[key]
    return None


@register_extractor(
    "intel-8051",
    families=_8051_FAMILIES,
)
class Intel8051Extractor:
    """8051-derivative extractor — Phase 4.2 implementation."""

    extractor_id: str = "intel-8051"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        header_path = _resolve_header(request)
        if header_path is None or not header_path.exists():
            available = sorted(request.source_paths)
            raise ValueError(
                f"intel-8051 extractor: cannot resolve SFR header for "
                f"{request.device}.  Pass --source intel-8051=<header> "
                f"or --source sfr-header=<header>.  "
                f"Got source keys: {available}"
            )
        text = header_path.read_text(encoding="utf-8", errors="replace")
        sfrs = parse_sfr_header(text)
        payload = _project_to_payload(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            sfrs=sfrs,
            source_path=header_path,
            revision=request.revision,
        )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="intel-8051",
                source_path=str(header_path),
                revision=request.revision,
            ),
            warnings=(
                "8051 extractor: bank-switching + indirect "
                "addressing not yet emitted — Phase 4.2 follow-up.",
            ),
        )


__all__ = ["Intel8051Extractor", "Sfr", "parse_sfr_header"]
