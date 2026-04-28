"""Microchip PIC extractor — `add-microchip-pic-extractor`
(Phase 3.1).  Scaffold; full DFP-pack + per-arch IR projection
lands in Phase 3.1 follow-up sessions.

Coverage target (~2,150 chips):

* PIC8/16/18 (~1,500 chips, Harvard 8-bit ISA)
* PIC24 + dsPIC33 (~500 chips, modified Harvard 16-bit)
* PIC32MX/MZ/MK (~150 chips, MIPS)

The implementation reuses the ATDF parser shared with AVR + SAM
extraction (Phase 1.2's `microchip_dfp/atdf.py` split).  This
scaffold registers the extractor binding (so the resolver picks
PIC families correctly) and surfaces a discoverable
NotImplementedError until the per-arch IR projection lands.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)

# Family identifiers for the three PIC arch buckets — used for
# registry binding so bulk discovery (Phase 2.1) can route each
# bucket to its eventual per-arch implementation.
PIC8_FAMILIES = ("pic12f", "pic16f", "pic18")
PIC24_FAMILIES = ("pic24f", "dspic33")
PIC32_FAMILIES = ("pic32mx", "pic32mz", "pic32mk")


_ALL_PIC_FAMILIES = (*PIC8_FAMILIES, *PIC24_FAMILIES, *PIC32_FAMILIES)


@register_extractor(
    "microchip-pic",
    families=tuple(("microchip", fam) for fam in _ALL_PIC_FAMILIES),
)
class MicrochipPicExtractor:
    """Microchip PIC extractor — Phase 3.1 scaffold."""

    extractor_id: str = "microchip-pic"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "Microchip PIC extractor is not yet implemented — "
            f"family {request.family!r} is reserved for "
            "`add-microchip-pic-extractor` (Phase 3.1).  Coverage "
            "target: PIC8/16/18 (~1,500), PIC24/dsPIC33 (~500), "
            "PIC32MX/MZ/MK (~150) = ~2,150 chips.  Implementation "
            "reuses Phase 1.2's microchip_dfp/atdf.py parser.  "
            "See ROADMAP.md."
        )


__all__ = ["MicrochipPicExtractor", "PIC8_FAMILIES", "PIC24_FAMILIES", "PIC32_FAMILIES"]
