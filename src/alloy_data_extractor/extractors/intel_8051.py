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

Phase 2 extends the parser with two vendor extensions:

* **SFR bank / page tracking** — modern 8051 derivatives (Nuvoton
  N76/N79, EFM8) place a second SFR plane behind a TA-protected
  page-select register.  Headers express the boundary either via
  comment markers (``// SFR Page 1``, ``/* page 1 */``) or via
  SDCC's ``#pragma sfr_bank`` directive.  We track the current
  bank linearly through the file and stamp each SFR with its
  ``bank`` index.
* **Indirect-addressing decoration** — SDCC keyword decorators
  (``__data``, ``__idata``, ``__xdata``, ``__pdata``, ``__bdata``)
  preceding a declaration stamp ``addressing_mode`` so downstream
  consumers can route the right load/store sequence.

Output shape:

* `peripherals`: each SFR group (SFR name prefix → distinct
  peripheral) becomes one peripheral row at its lowest SFR
  address.
* `registers`: each SFR becomes one register row carrying
  ``bank`` and ``addressing_mode`` columns.

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


# Match `__sfr __at (0x80) NAME;` and `sfr __at (0x80) NAME;`.
# The optional ``__(data|idata|xdata|pdata|bdata)`` prefix lets us
# capture SDCC addressing-mode decorators in the same pass.
_SFR_PATTERN = re.compile(
    r"""
    (?:(?P<addr_mode>__(?:i|x|p|b)?data)\s+)?  # optional SDCC mode
    (?:__)?sfr (?P<width>16)?           # __sfr / sfr / sfr16
    \s+ (?:__)?at \s* \(?\s*           # __at(  /  at  / __at
    (?P<addr>0x[0-9a-fA-F]+)           # the address literal
    \s*\)?\s*                          # closing )
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    \s* ;
    """,
    re.VERBOSE,
)

_SBIT_PATTERN = re.compile(
    r"""
    (?:(?P<addr_mode>__(?:i|x|p|b)?data)\s+)?
    (?:__)?sbit
    \s+ (?:__)?at \s* \(?\s*
    (?P<addr>0x[0-9a-fA-F]+)
    \s*\)?\s*
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    \s* ;
    """,
    re.VERBOSE,
)

# Recognise ``// SFR Page 1``, ``/* page 1 */``, ``// bank 1`` etc.
# Captures a single integer page index.
_BANK_MARKER_RE = re.compile(
    r"""(?://|/\*)\s*
        (?:SFR\s+)?
        (?:Page|Bank)\s*[:#]?\s*(?P<bank>\d+)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# `#pragma sfr_bank 1` / `#pragma sfr_page 0` directives.
_PRAGMA_BANK_RE = re.compile(
    r"""\#pragma\s+sfr_(?:bank|page)\s+(?P<bank>\d+)""",
    re.VERBOSE | re.IGNORECASE,
)


_ADDR_MODE_FROM_KEYWORD = {
    "__data": "direct",
    "__idata": "indirect",
    "__xdata": "external",
    "__pdata": "paged",
    "__bdata": "bit-addressable",
}


@dataclass(frozen=True, slots=True)
class Sfr:
    """One Special-Function Register."""

    name: str
    address: int
    is_bit: bool = False
    width_bits: int = 8
    bank: int = 0
    addressing_mode: str = "direct"


def _is_16bit_match(match: re.Match[str]) -> bool:
    """The width capture group is set when ``sfr16`` was matched."""
    width_group = match.groupdict().get("width")
    return width_group == "16"


def _addr_mode_for(match: re.Match[str], default: str) -> str:
    keyword = match.groupdict().get("addr_mode")
    if not keyword:
        return default
    return _ADDR_MODE_FROM_KEYWORD.get(keyword, default)


def parse_sfr_header(text: str) -> tuple[Sfr, ...]:
    """Parse an 8051 SFR header into typed :class:`Sfr` rows.

    Walks the file line-by-line tracking the current SFR bank
    (driven by ``// page <n>`` comments and ``#pragma sfr_bank``
    directives) so each SFR declaration is stamped with the
    bank that was active at its position.

    SDCC's ``__data``/``__idata``/``__xdata``/``__pdata``/
    ``__bdata`` keyword on a declaration overrides
    ``addressing_mode`` for that SFR.  Bit registers default to
    ``addressing_mode="bit"``.
    """
    sfrs: list[Sfr] = []
    seen: set[tuple[str, int, int]] = set()
    current_bank = 0

    for line in text.splitlines():
        bank_match = _BANK_MARKER_RE.search(line)
        if bank_match:
            current_bank = int(bank_match.group("bank"))
            # The marker line might also carry a declaration after
            # the comment (rare but harmless to keep scanning).
        pragma_match = _PRAGMA_BANK_RE.search(line)
        if pragma_match:
            current_bank = int(pragma_match.group("bank"))

        for match in _SFR_PATTERN.finditer(line):
            addr = int(match.group("addr"), 16)
            name = match.group("name")
            width = 16 if _is_16bit_match(match) else 8
            mode = _addr_mode_for(match, default="direct")
            key = (name, addr, current_bank)
            if key in seen:
                continue
            seen.add(key)
            sfrs.append(
                Sfr(
                    name=name,
                    address=addr,
                    width_bits=width,
                    bank=current_bank,
                    addressing_mode=mode,
                )
            )

        for match in _SBIT_PATTERN.finditer(line):
            addr = int(match.group("addr"), 16)
            name = match.group("name")
            mode = _addr_mode_for(match, default="bit")
            key = (name, addr, current_bank)
            if key in seen:
                continue
            seen.add(key)
            sfrs.append(
                Sfr(
                    name=name,
                    address=addr,
                    is_bit=True,
                    width_bits=1,
                    bank=current_bank,
                    addressing_mode=mode,
                )
            )

    return tuple(sorted(sfrs, key=lambda s: (s.bank, s.address, s.name)))


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
    # Group SFRs by (bank, peripheral) → one peripheral row at the
    # lowest address.  Two SFRs that collide on (name, address) but
    # in different banks remain distinct peripherals so consumers
    # can route through the right page-select sequence.
    by_peripheral: dict[tuple[int, str], list[Sfr]] = {}
    for sfr in sfrs:
        if sfr.is_bit:
            continue
        group = _peripheral_group(sfr.name)
        by_peripheral.setdefault((sfr.bank, group), []).append(sfr)

    peripherals: list[dict[str, Any]] = []
    for (bank, group_name), group_sfrs in sorted(by_peripheral.items()):
        entry: dict[str, Any] = {
            "name": group_name,
            "base_address": min(s.address for s in group_sfrs),
            "kind": "sfr-group",
        }
        if bank:
            entry["bank"] = bank
        peripherals.append(entry)

    registers = [
        {
            "name": s.name,
            "address": s.address,
            "width_bits": s.width_bits,
            "is_bit": s.is_bit,
            "bank": s.bank,
            "addressing_mode": s.addressing_mode,
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
        warnings: list[str] = []
        banks_seen = {s.bank for s in sfrs}
        if banks_seen == {0}:
            warnings.append(
                "8051 extractor: header carries no SFR bank/page "
                "markers — single-bank parse.  This is expected for "
                "classic 8051 cores; modern N76/N79/EFM8 should "
                "expose multiple banks via `// page <n>` comments "
                "or `#pragma sfr_bank <n>` directives."
            )
        modes_seen = {s.addressing_mode for s in sfrs}
        if not modes_seen.issubset({"direct", "bit"}):
            warnings.append(
                "8051 extractor: header decorates SFRs with SDCC "
                "addressing-mode keywords; payload's "
                "`registers[*].addressing_mode` reflects them."
            )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="intel-8051",
                source_path=str(header_path),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = ["Intel8051Extractor", "Sfr", "parse_sfr_header"]
