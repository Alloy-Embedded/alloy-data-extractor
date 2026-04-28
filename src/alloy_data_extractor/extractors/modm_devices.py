"""modm-devices XML enrichment extractor —
`migrate-modm-enrichment-extractor` (Phase 1.7) scaffold.

modm-devices is a *secondary* extractor: it does not produce a
canonical YAML on its own — it produces an enrichment record
that the cross-source merge stage (Phase 2.2) folds onto a
primary extraction.  Until the merge stage exists, the STM32
extractor will call this module directly as transitional
plumbing.

Registration omits ``vendors=`` / ``families=`` because this
isn't picked by the resolver — it's a manual-call dependency of
the STM32 path.  The protocol decorator requires at least one
binding, so we declare a synthetic ``modm-only`` family that
will never be looked up via ``resolve_extractor(...)`` but
keeps the registry shape consistent.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "modm-devices",
    families=(("__modm_secondary__", "__modm_secondary__"),),
)
class ModmEnrichmentExtractor:
    """modm-devices XML enrichment — Phase 1.7 scaffold.

    Future work: implement an `EnrichmentExtractor` subprotocol
    that returns an `EnrichmentRecord` (DMA bindings + clock
    nodes + AF tables) rather than a full canonical-IR payload.
    """

    extractor_id: str = "modm-devices"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "modm-devices enrichment extractor is not yet implemented — "
            "Phase 1.7 (`migrate-modm-enrichment-extractor`) ports "
            "alloy-codegen/src/alloy_codegen/sources/modm_devices.py "
            "(529 LOC).  The full integration depends on Phase 2.2's "
            "cross-source merge engine.  "
            "See ROADMAP.md and PHASE_1_HANDOFF.md."
        )


__all__ = ["ModmEnrichmentExtractor"]
