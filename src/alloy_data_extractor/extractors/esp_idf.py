"""Espressif ESP-IDF extractor — `migrate-espressif-esp-idf-extractor`
(Phase 1.4) scaffold.

Claims `(espressif, esp32)`, `(espressif, esp32c3)`,
`(espressif, esp32s3)`.  The full ESP-IDF SOC header parser port
lands in Phase 1.4.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "esp-idf",
    families=(
        ("espressif", "esp32"),
        ("espressif", "esp32c3"),
        ("espressif", "esp32s3"),
    ),
)
class EspIdfExtractor:
    """Espressif ESP-IDF extractor — Phase 1.4 scaffold."""

    extractor_id: str = "esp-idf"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "Espressif ESP-IDF extractor is not yet implemented — "
            "Phase 1.4 (`migrate-espressif-esp-idf-extractor`) ports "
            "alloy-codegen/src/alloy_codegen/sources/esp_idf.py.  "
            "See ROADMAP.md and PHASE_1_HANDOFF.md."
        )


__all__ = ["EspIdfExtractor"]
