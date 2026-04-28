"""TI MSP430 extractor — `add-msp430-extractor` (Phase 3.3).
Scaffold.

Reads TI SysConfig metadata + MSP430 device-headers and
projects them into canonical YAML.  ~200 chips covered when
fully implemented.

The schema (`identity.core: msp430`) is open for the new value;
no schema change is required to admit MSP430 — the existing
``"type": "string"`` core field accepts it as-is.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)

# Canonical family identifier for MSP430 — every variant lands
# under this single bucket; series (FR5xxx, F2xxx, etc.) is in
# the device name itself.
MSP430_FAMILIES = ("msp430",)


@register_extractor(
    "msp430",
    families=tuple(("ti", fam) for fam in MSP430_FAMILIES),
)
class Msp430Extractor:
    """TI MSP430 extractor — Phase 3.3 scaffold."""

    extractor_id: str = "msp430"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "TI MSP430 extractor is not yet implemented — "
            "`add-msp430-extractor` (Phase 3.3).  Implementation "
            "parses TI SysConfig metadata + MSP430 device-headers "
            "into canonical YAML; ~200 chips covered.  Request was "
            f"for {request.vendor}/{request.family}/{request.device}.  "
            "See ROADMAP.md."
        )


__all__ = ["Msp430Extractor", "MSP430_FAMILIES"]
