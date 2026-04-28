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

Per-arch IR projection nuances (banked memory, indirect
addressing, dsPIC's DSP-related SFRs) are handled by per-arch
overrides at extraction time — for v1 we delegate everything
to the shared ATDF parser and carry an arch-specific
`identity.core` value.
"""

from __future__ import annotations

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
            "memories": [],
            "peripherals": peripherals,
            "interrupts": interrupts,
        }
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="microchip-pic",
                source_path=str(atdf_path),
                revision=request.revision,
            ),
            warnings=(
                "Microchip PIC extractor: arch-specific quirks "
                "(banked memory, indirect addressing, dsPIC DSP "
                "SFRs) handled at codegen consumer side until "
                "Phase 3.1 follow-up implements per-arch projection.",
            ),
        )


__all__ = [
    "MicrochipPicExtractor",
    "PIC8_FAMILIES",
    "PIC24_FAMILIES",
    "PIC32_FAMILIES",
]
