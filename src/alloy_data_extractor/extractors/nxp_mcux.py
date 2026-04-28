"""NXP MCUXpresso extractor — `migrate-nxp-mcux-extractor` (Phase 1.3).

Reads the per-device XML descriptors from `nxp-mcux-soc-svd`
(the upstream NXP repo that ships
``MIMXRT1062/MIMXRT1062.xml`` etc).  The XML format is
SVD-compatible — the extractor reuses the CMSIS-SVD parser.

What this DOES today:
* Resolve the per-device XML from the NXP SoC SVD source root.
* Extract peripherals + interrupts + register layout.
* Stamp `provenance.source_id = "nxp-mcux"`.

What it does NOT do yet:
* Apply iMXRT IOMUX / GPIO pin tables that the codegen-side
  ``populate-imxrt-iomux-gpio-pins`` provides.  Those still
  layer in via the codegen legacy path.
"""

from __future__ import annotations

from pathlib import Path

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)
from alloy_data_extractor.extractors.cmsis_svd import extract_device as _cmsis_svd_extract


def _resolve_svd_path(request: ExtractionRequest) -> Path | None:
    """Resolve the NXP per-device XML.

    NXP's directory layout is ``<root>/<UPPERDEVICE>/<UPPERDEVICE>.xml``
    (e.g. ``MIMXRT1062/MIMXRT1062.xml``).
    """
    if "cmsis-svd" in request.source_paths:
        return request.source_paths["cmsis-svd"]
    for key in ("nxp-mcux", "nxp-mcux-soc-svd"):
        if key in request.source_paths:
            upper = request.device.upper()
            candidate = request.source_paths[key] / upper / f"{upper}.xml"
            if candidate.exists():
                return candidate
    return None


@register_extractor(
    "nxp-mcux",
    families=(("nxp", "imxrt1060"),),
)
class NxpMcuxExtractor:
    """NXP MCUXpresso extractor — Phase 1.3 implementation."""

    extractor_id: str = "nxp-mcux"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        svd_path = _resolve_svd_path(request)
        if svd_path is None or not svd_path.exists():
            available_keys = sorted(request.source_paths)
            raise ValueError(
                f"nxp-mcux extractor: cannot resolve SoC XML for "
                f"{request.device}.  Pass --source cmsis-svd=<path-to-xml> "
                f"or --source nxp-mcux=<nxp-mcux-soc-svd-root>.  "
                f"Got source keys: {available_keys}"
            )
        legacy = _cmsis_svd_extract(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            svd_path=svd_path,
            revision=request.revision,
        )
        payload = dict(legacy.payload)
        provenance = dict(payload.get("provenance", {}))
        provenance["source_id"] = "nxp-mcux"
        provenance["source_path"] = str(svd_path)
        payload["provenance"] = provenance

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="nxp-mcux",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=(
                "NXP MCUX extractor: IOMUX / GPIO pin tables not "
                "yet emitted — Phase 1.3 follow-up ports them.",
            ),
        )


__all__ = ["NxpMcuxExtractor"]
