"""Microchip DFP/ATDF extractor — `migrate-microchip-dfp-extractor`
(Phase 1.2) scaffold.

Claims `(microchip, avr-da)` and `(microchip, same70)`.  The
full ATDF parser port (the largest single file in
alloy-codegen/sources/, 1,053 LOC) lands in Phase 1.2 split
into `atdf.py`, `avr.py`, and `sam.py` so PIC support
(Phase 3.1) can reuse `atdf.py` without forking.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "microchip-dfp",
    families=(
        ("microchip", "avr-da"),
        ("microchip", "same70"),
    ),
)
class MicrochipDfpExtractor:
    """Microchip DFP/ATDF extractor — Phase 1.2 scaffold."""

    extractor_id: str = "microchip-dfp"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "Microchip DFP extractor is not yet implemented — "
            "Phase 1.2 (`migrate-microchip-dfp-extractor`) ports "
            "alloy-codegen/src/alloy_codegen/sources/microchip_dfp.py "
            "(1,053 LOC), splitting it into atdf.py + avr.py + sam.py "
            "so PIC support (Phase 3.1) can reuse atdf.py.  "
            "See ROADMAP.md and PHASE_1_HANDOFF.md."
        )


__all__ = ["MicrochipDfpExtractor"]
