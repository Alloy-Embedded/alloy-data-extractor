"""RP2040 extractor — `migrate-rp2040-pico-sdk-extractor` (Phase 1.5) scaffold.

Deferring stub: registration is in place so the resolver picks
this extractor for `(raspberrypi, rp2040)` ahead of CMSIS-SVD's
vendor-wide binding.  The full Pico SDK header parser port lands
in Phase 1.5 — until then ``extract()`` raises a discoverable
``NotImplementedError``.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "pico-sdk",
    families=(("raspberrypi", "rp2040"),),
)
class PicoSdkExtractor:
    """RP2040 extractor — Phase 1.5 scaffold."""

    extractor_id: str = "pico-sdk"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "RP2040 extractor is not yet implemented — Phase 1.5 "
            "(`migrate-rp2040-pico-sdk-extractor`) ports the Pico "
            "SDK header parser from "
            "alloy-codegen/src/alloy_codegen/sources/pico_sdk.py.  "
            "See ROADMAP.md and PHASE_1_HANDOFF.md."
        )


__all__ = ["PicoSdkExtractor"]
