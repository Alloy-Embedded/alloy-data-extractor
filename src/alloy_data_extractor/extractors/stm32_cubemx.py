"""STM32CubeMX MCU database extractor —
`add-stm32-cubemx-db-extractor` (Phase 3.2).  Scaffold.

Reads ``db/mcu/*.xml`` from a CubeMX installation to enrich
STM32 chips with:

* Pinmux alternate-function tables.
* Clock-tree edges.
* DMA request matrix.

Registered as a **secondary** EnrichmentExtractor — does not
produce its own canonical YAML; composes with the primary STM32
extractor (Phase 1.1) via the merge engine (Phase 2.2).

The reference :data:`STM32_MERGE_POLICY` already declares
CubeMX as the authoritative source for `pins`, `clock_nodes`,
`dma_requests`.  This scaffold is the registration entry that
`run_bulk` and the future cross-source merge driver need to
discover the extractor at module-import time.

License posture: the extractor refuses to bundle the CubeMX DB
itself — the user supplies the path via
``--source stm32cubemx-db=<path>``.  The pin manifest records
the supported CubeMX version without distributing the binary.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "stm32-cubemx",
    # Synthetic family so the extractor doesn't accidentally
    # win the resolver for ST families — it's an enrichment, not
    # a primary.  The merge engine looks it up by id, not via
    # resolve_extractor.
    families=(("__cubemx_secondary__", "__cubemx_secondary__"),),
)
class Stm32CubeMxExtractor:
    """STM32 CubeMX enrichment — Phase 3.2 scaffold."""

    extractor_id: str = "stm32-cubemx"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "STM32 CubeMX enrichment extractor is not yet "
            "implemented — `add-stm32-cubemx-db-extractor` "
            "(Phase 3.2).  Implementation parses CubeMX DB XML "
            "(db/mcu/*.xml) for pinmux + clock-tree + DMA matrix. "
            f"Request was for {request.vendor}/{request.family}/{request.device}.  "
            "See ROADMAP.md."
        )


__all__ = ["Stm32CubeMxExtractor"]
