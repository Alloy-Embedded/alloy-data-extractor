"""NXP MCUXpresso extractor — `migrate-nxp-mcux-extractor` (Phase 1.3)
+ `complete-imxrt1060-register-coverage`.

Reads the per-device XML descriptors from `nxp-mcux-soc-svd`
(the upstream NXP repo that ships
``MIMXRT1062/MIMXRT1062.xml`` etc).  The XML format is
SVD-compatible — the extractor reuses the CMSIS-SVD parser.

Surface:

* Resolves the per-device XML from the NXP SoC SVD source root.
* Extracts peripherals + interrupts + the full register tree
  (registers + register_fields) via the shared cmsis-svd
  walker, with `<derivedFrom>`, `<dim>` arrays, and
  `bitOffset/bitWidth` / `bitRange` / `lsb-msb` field positions
  all resolved.
* Stamps top-level provenance with
  ``source_id = "nxp-mcux"`` and rewrites every per-row
  provenance source_id to ``"nxp-mcux-soc-svd"`` so reviewers
  can trace each peripheral / register / field row back to the
  upstream NXP SoC SVD pin.

What it does NOT do yet:
* Apply iMXRT IOMUX / GPIO pin tables — IOMUX is sourced from
  ``MIMXRT1062.h`` (C header) rather than the SoC XML and is a
  separate workstream.
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

        # Per-row provenance: rewrite the source_id stamped by the
        # cmsis-svd walker ("cmsis-svd") to "nxp-mcux-soc-svd" — the
        # source-pin id from data/source_pins.toml that
        # complete-imxrt1060-register-coverage calls out.  Reviewers
        # auditing a YAML can trace any peripheral/register/field
        # row back to the upstream NXP repo pin.
        for row_field in ("peripherals", "interrupts", "registers", "register_fields"):
            for row in payload.get(row_field, []):
                row_prov = row.get("provenance")
                if isinstance(row_prov, dict):
                    row_prov["source_id"] = "nxp-mcux-soc-svd"

        warnings: list[str] = []
        if not payload.get("registers"):
            warnings.append(
                "NXP MCUX extractor: SoC XML carried no register "
                "tree — payload's `registers` / `register_fields` "
                "are empty."
            )
        warnings.append(
            "NXP MCUX extractor: IOMUX / GPIO pin tables sourced from "
            "MIMXRT1062.h are out of scope; populate via a separate "
            "follow-up workstream when needed."
        )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="nxp-mcux",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = ["NxpMcuxExtractor"]
