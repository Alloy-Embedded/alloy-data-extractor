"""NXP MCUXpresso extractor — `migrate-nxp-mcux-extractor` (Phase 1.3) scaffold.

Deferring stub: claims `(nxp, imxrt1060)` ahead of the CMSIS-SVD
catch-all.  The full MCUXpresso SDK parser port lands in
Phase 1.3.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "nxp-mcux",
    families=(("nxp", "imxrt1060"),),
)
class NxpMcuxExtractor:
    """NXP MCUXpresso extractor — Phase 1.3 scaffold."""

    extractor_id: str = "nxp-mcux"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "NXP MCUX extractor is not yet implemented — Phase 1.3 "
            "(`migrate-nxp-mcux-extractor`) ports "
            "alloy-codegen/src/alloy_codegen/sources/nxp_mcux.py.  "
            "See ROADMAP.md and PHASE_1_HANDOFF.md."
        )


__all__ = ["NxpMcuxExtractor"]
