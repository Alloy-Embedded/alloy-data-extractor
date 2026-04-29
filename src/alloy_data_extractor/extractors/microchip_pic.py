"""Microchip PIC extractor — `add-microchip-pic-extractor`
(Phase 3.1).

Reuses the Phase 1.2 Microchip-DFP ATDF parser to admit
Microchip PIC families: PIC8/16/18 + PIC24/dsPIC33 +
PIC32MX/MZ/MK.  Microchip ships ATDF for every PIC variant via
the MPLAB X DFP packs — the format is identical to the AVR/SAM
ATDF the Phase 1.2 implementation already parses.

Coverage target (~2,150 chips):

* PIC8/16/18 — Harvard 8-bit (~1,500 chips)
* PIC24 + dsPIC33 — modified Harvard 16-bit (~500 chips)
* PIC32MX/MZ/MK — MIPS (~150 chips)

Phase 2 — per-arch IR projection:

* PIC8/16/18 (Harvard 8-bit): bank classification of GPR / SFR
  segments by name pattern (``BANK<N>_GPR``, ``BANK<N>_SFR``).
* PIC24 / dsPIC33 (modified Harvard 16-bit): indirect-pointer
  register carve-out (W register file, TBLPAG, DSRPAG, DSWPAG,
  PSVPAG, NVMSRCADRL/H).
* dsPIC33 (DSP): coprocessor-SFR carve-out (CORCON, ACCAL/H/U,
  DCOUNT, DOSTART/L/H, DOEND/L/H, MODCON).
* PIC32MX/MZ/MK (MIPS): CP0 (Coprocessor-0) register carve-out
  identified via ``<address-space id="cp0">``.

Each carve-out lives under ``arch_extensions``::

    arch_extensions:
      banked_memory:
        - { bank: 0, kind: GPR, start: 0x20, size: 0x60 }
      indirect_pointer_registers:
        - { name: TBLPAG, peripheral: PMD }
      dsp_sfrs:
        - { name: CORCON, peripheral: CPU }
      cp0_registers:
        - { name: STATUS, address: 0xBF80F000 }
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)
from alloy_data_extractor.extractors.microchip_dfp import (
    _atdf_core_to_canonical,
    _memory_regions,
    _peripheral_records,
)

PIC8_FAMILIES = ("pic12f", "pic16f", "pic18")
PIC24_FAMILIES = ("pic24f", "dspic33")
PIC32_FAMILIES = ("pic32mx", "pic32mz", "pic32mk")
_ALL_PIC_FAMILIES = (*PIC8_FAMILIES, *PIC24_FAMILIES, *PIC32_FAMILIES)


# Per-family default core hint when the ATDF doesn't expose one
# (older PIC ATDFs sometimes omit the `architecture` attribute).
_FAMILY_CORE_DEFAULT = {
    "pic12f": "pic12f",
    "pic16f": "pic16f",
    "pic18": "pic18",
    "pic24f": "pic24f",
    "dspic33": "dspic33",
    "pic32mx": "pic32mx",
    "pic32mz": "pic32mz",
    "pic32mk": "pic32mk",
}


# ---------------------------------------------------------------------------
# Per-arch carve-out helpers
# ---------------------------------------------------------------------------


_BANK_NAME_RE = re.compile(
    r"^BANK\s*(?P<index>\d+)\s*_?(?P<kind>GPR|SFR|RAM|MIRROR)?",
    re.IGNORECASE,
)


def _classify_pic8_banks(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project data-space segments named ``BANK<N>_*`` into a flat
    bank table.  Other memory regions (``COMMON``, ``SFR``,
    ``LINEAR``) flow through unchanged.

    Returns one row per recognized bank; rows are sorted by bank
    index then by base address.  Entries that don't match the
    bank-name regex are silently skipped (they remain visible in
    the unfiltered ``memories`` list).
    """
    banks: list[dict[str, Any]] = []
    for memory in memories:
        if memory["address_space"] != "data":
            continue
        match = _BANK_NAME_RE.match(memory["name"])
        if not match:
            continue
        banks.append(
            {
                "bank": int(match.group("index")),
                "kind": (match.group("kind") or "").upper(),
                "name": memory["name"],
                "base_address": memory["base_address"],
                "size_bytes": memory["size_bytes"],
            }
        )
    banks.sort(key=lambda r: (r["bank"], r["base_address"], r["name"]))
    return banks


# Indirect-pointer registers carry data-space paging on PIC24 /
# dsPIC33.  They live alongside regular SFRs in the ATDF; we
# detect them by name pattern so the consumer can route the right
# load/store sequence (``MOV.D Wn, …`` vs ``TBLRDH.B``).
_INDIRECT_POINTER_NAMES = frozenset(
    {
        "TBLPAG",
        "DSRPAG",
        "DSWPAG",
        "PSVPAG",
        "NVMSRCADRL",
        "NVMSRCADRH",
        "RPINR0",  # Pin remap registers — peripheral pin select.
    }
)
_INDIRECT_POINTER_PATTERN = re.compile(r"^W(\d+)$")  # W0..W15 register file


# dsPIC33 DSP-engine SFRs.  Cannot be mistaken for general
# peripherals — they live in the CPU SFR block but the codegen
# path for accessing them is different (DSP-specific instructions).
_DSP_SFR_NAMES = frozenset(
    {
        "CORCON",
        "ACCAL", "ACCAH", "ACCAU",
        "ACCBL", "ACCBH", "ACCBU",
        "ACCCL", "ACCCH", "ACCCU",
        "DCOUNT",
        "DOSTART", "DOSTARTL", "DOSTARTH",
        "DOEND", "DOENDL", "DOENDH",
        "MODCON",
        "XMODSRT", "XMODEND",
        "YMODSRT", "YMODEND",
        "XBREV",
    }
)


def _classify_pic24_indirect_pointers(
    peripherals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter peripherals whose name matches an indirect-pointer
    or W-register convention.  We carry just the name + base so
    the consumer can synthesize the right page-protected access
    sequence."""
    rows: list[dict[str, Any]] = []
    for peri in peripherals:
        name = peri["name"]
        if name in _INDIRECT_POINTER_NAMES or _INDIRECT_POINTER_PATTERN.match(name):
            rows.append(
                {
                    "name": name,
                    "base_address": peri["base_address"],
                    "kind": "indirect-pointer",
                }
            )
    rows.sort(key=lambda r: (r["base_address"], r["name"]))
    return rows


def _classify_dspic_dsp_sfrs(
    peripherals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carve out dsPIC33 DSP-engine SFRs.  Same shape as
    indirect-pointer rows — name + base — annotated with
    ``kind="dsp-coprocessor"``."""
    rows: list[dict[str, Any]] = []
    for peri in peripherals:
        if peri["name"] in _DSP_SFR_NAMES:
            rows.append(
                {
                    "name": peri["name"],
                    "base_address": peri["base_address"],
                    "kind": "dsp-coprocessor",
                }
            )
    rows.sort(key=lambda r: (r["base_address"], r["name"]))
    return rows


def _classify_pic32_cp0(
    device: ET.Element,
    memories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project PIC32 MIPS Coprocessor-0 (CP0) registers.

    CP0 lives under its own ``<address-space id="cp0">`` in PIC32
    ATDFs.  Each register shows up as a ``<memory-segment>``
    inside that block; the consumer needs them to be visible
    *separately* from the regular MMIO peripherals because CP0
    access uses ``mtc0``/``mfc0`` instructions, not memory-mapped
    loads/stores.
    """
    rows: list[dict[str, Any]] = []
    for memory in memories:
        if memory["address_space"] != "cp0":
            continue
        rows.append(
            {
                "name": memory["name"],
                "address": memory["base_address"],
                "size": memory["size_bytes"],
                "kind": "cp0-register",
            }
        )

    # Some older PIC32 ATDFs flag CP0 modules as `coprocessor`
    # peripherals instead.  Look for those too.
    peripherals_root = device.find("peripherals")
    if peripherals_root is not None:
        for module in peripherals_root.findall("module"):
            module_name = (module.get("name") or "").upper()
            if "COPROCESSOR" not in module_name and "CP0" not in module_name:
                continue
            for instance in module.findall("instance"):
                instance_name = instance.get("name", "")
                if not instance_name:
                    continue
                rg = instance.find("register-group")
                if rg is None:
                    continue
                addr_str = rg.get("offset")
                addr = int(addr_str, 0) if addr_str else 0
                rows.append(
                    {
                        "name": instance_name,
                        "address": addr,
                        "size": 0,
                        "kind": "cp0-register",
                    }
                )
    rows.sort(key=lambda r: (r["address"], r["name"]))
    return rows


def _arch_extensions(
    *,
    family: str,
    device: ET.Element,
    memories: list[dict[str, Any]],
    peripherals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build per-arch ``arch_extensions`` block.  Empty extensions
    are omitted so the payload stays tight — consumers can iterate
    the keys to detect which carve-outs are present."""
    extensions: dict[str, Any] = {}
    if family in PIC8_FAMILIES:
        banked = _classify_pic8_banks(memories)
        if banked:
            extensions["banked_memory"] = banked
    if family in PIC24_FAMILIES:
        indirect = _classify_pic24_indirect_pointers(peripherals)
        if indirect:
            extensions["indirect_pointer_registers"] = indirect
        if family == "dspic33":
            dsp = _classify_dspic_dsp_sfrs(peripherals)
            if dsp:
                extensions["dsp_sfrs"] = dsp
    if family in PIC32_FAMILIES:
        cp0 = _classify_pic32_cp0(device, memories)
        if cp0:
            extensions["cp0_registers"] = cp0
    return extensions


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_atdf_path(request: ExtractionRequest) -> Path | None:
    """Resolve the ATDF path from the request's source paths.

    * ``source_paths["atdf"]`` — direct path.
    * ``source_paths["microchip-pic"]`` — DFP-style cache root.
    """
    if "atdf" in request.source_paths:
        return request.source_paths["atdf"]
    for key in ("microchip-pic", "microchip-dfp"):
        if key in request.source_paths:
            upper = request.device.upper()
            for atdf in request.source_paths[key].rglob(f"{upper}.atdf"):
                return atdf
    return None


# ---------------------------------------------------------------------------
# Extractor protocol adapter
# ---------------------------------------------------------------------------


@register_extractor(
    "microchip-pic",
    families=tuple(("microchip", fam) for fam in _ALL_PIC_FAMILIES),
)
class MicrochipPicExtractor:
    """Microchip PIC extractor — Phase 3.1 implementation."""

    extractor_id: str = "microchip-pic"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        atdf_path = _resolve_atdf_path(request)
        if atdf_path is None or not atdf_path.exists():
            available = sorted(request.source_paths)
            raise ValueError(
                f"microchip-pic extractor: cannot resolve ATDF for "
                f"{request.device}.  Pass --source atdf=<path> or "
                f"--source microchip-pic=<dfp-cache-root>.  "
                f"Got source keys: {available}"
            )
        root = ET.parse(atdf_path).getroot()
        device = root.find(".//device")
        if device is None:
            raise ValueError(
                f"microchip-pic extractor: ATDF at {atdf_path} has no <device> element."
            )
        atdf_arch = device.get("architecture")
        core = _atdf_core_to_canonical(atdf_arch)
        if not core:
            core = _FAMILY_CORE_DEFAULT.get(request.family, "")
        peripherals, interrupts = _peripheral_records(device)
        memories = _memory_regions(device)
        extensions = _arch_extensions(
            family=request.family,
            device=device,
            memories=memories,
            peripherals=peripherals,
        )

        payload: dict[str, Any] = {
            "schema_version": "1.3.0",
            "identity": {
                "vendor": request.vendor,
                "family": request.family,
                "device": request.device,
                "package": "",
                "core": core,
                "summary": f"Admitted via Microchip DFP/ATDF ({atdf_path.name}).",
            },
            "provenance": {
                "source_id": "microchip-pic",
                "source_path": str(atdf_path),
                "patch_ids": [],
            },
            "memories": memories,
            "peripherals": peripherals,
            "interrupts": interrupts,
        }
        if extensions:
            payload["arch_extensions"] = extensions

        warnings: list[str] = []
        if not memories:
            warnings.append(
                "microchip-pic: ATDF carries no <address-spaces>/"
                "<memory-segment> blocks — payload's `memories` "
                "list is empty.  Verify the DFP pack version."
            )
        if request.family in PIC8_FAMILIES and "banked_memory" not in extensions:
            warnings.append(
                "microchip-pic: PIC8 family but no BANK<N>_* "
                "memory segments found — banked-memory carve-out "
                "is empty.  Older PIC8 packs may name banks "
                "differently."
            )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="microchip-pic",
                source_path=str(atdf_path),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = [
    "MicrochipPicExtractor",
    "PIC8_FAMILIES",
    "PIC24_FAMILIES",
    "PIC32_FAMILIES",
    "_arch_extensions",
    "_classify_dspic_dsp_sfrs",
    "_classify_pic24_indirect_pointers",
    "_classify_pic32_cp0",
    "_classify_pic8_banks",
]
