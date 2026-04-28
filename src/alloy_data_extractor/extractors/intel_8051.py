"""8051-derivative extractor — `add-8051-extractor` (Phase 4.2).
Scaffold.

Covers Nuvoton N76 / N79, SiLabs EFM8, STC15W families
(~150 chips total).  The 8051 ISA has no MMU, no FPU, and a
flat memory model that doesn't fit cleanly into the canonical
``identity.core`` ARM-flavoured taxonomy — so we admit
``identity.core: i8051`` as the family-level marker.

Implementation reads per-vendor SDK headers (each vendor ships
its own register-definition format).  Until the parser ports
land, this scaffold registers the binding so bulk discovery
can route 8051 vendors to the eventual implementation.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)

# Per-vendor 8051 family identifiers.  Each vendor's series gets
# its own family entry — Nuvoton's N76 is a different SDK
# format from SiLabs' EFM8.
_8051_FAMILIES: tuple[tuple[str, str], ...] = (
    ("nuvoton", "n76"),
    ("nuvoton", "n79"),
    ("silabs", "efm8"),
    ("stc", "stc15w"),
)


@register_extractor(
    "intel-8051",
    families=_8051_FAMILIES,
)
class Intel8051Extractor:
    """8051-derivative extractor — Phase 4.2 scaffold."""

    extractor_id: str = "intel-8051"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "8051 extractor is not yet implemented — "
            "`add-8051-extractor` (Phase 4.2).  Implementation "
            "parses per-vendor SDK headers (Nuvoton N76 / N79, "
            "SiLabs EFM8, STC STC15W) into canonical YAML with "
            "identity.core=i8051.  Request was for "
            f"{request.vendor}/{request.family}/{request.device}.  "
            "See ROADMAP.md."
        )


__all__ = ["Intel8051Extractor"]
