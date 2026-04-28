"""Datasheet PDF scraper — `add-modm-data-pdf-extractor`
(Phase 4.1).  Scaffold.

Last-resort coverage for chips whose vendor publishes no
machine-readable source (no SVD, no ATDF, no DTS).  Approach:
modm-data-style template-driven scraping via pdfminer.six.

Every YAML produced by this extractor MUST carry
``provenance.confidence: low`` so the codegen consumer can
opt-in to low-confidence devices via a ``--accept-low-confidence``
flag.  Without that flag, low-confidence YAMLs are excluded
from emission.

Registered with a synthetic family — the extractor is invoked
explicitly per-template, not auto-resolved by vendor.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "datasheet-pdf",
    families=(("__pdf_scrape__", "__pdf_scrape__"),),
)
class DatasheetPdfExtractor:
    """PDF datasheet scraper — Phase 4.1 scaffold."""

    extractor_id: str = "datasheet-pdf"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "PDF datasheet scraper is not yet implemented — "
            "`add-modm-data-pdf-extractor` (Phase 4.1).  "
            "Implementation uses pdfminer.six + per-vendor "
            "templates under data/datasheet_templates/<vendor>.toml. "
            f"Request was for {request.vendor}/{request.family}/{request.device}.  "
            "Output YAMLs SHALL carry provenance.confidence=low.  "
            "See ROADMAP.md."
        )


__all__ = ["DatasheetPdfExtractor"]
