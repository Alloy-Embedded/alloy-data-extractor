"""RP2040 extractor — `migrate-rp2040-pico-sdk-extractor` (Phase 1.5).

Reads the SVD that ships inside the Pico SDK
(``src/rp2040/hardware_regs/RP2040.svd``) and projects it into a
canonical-IR-shaped payload.  Family-bound for
``(raspberrypi, rp2040)`` so the resolver picks this extractor
ahead of CMSIS-SVD's vendor-wide catch-all.

What this DOES today:
* Resolve the RP2040 SVD path from the Pico SDK source root
  (env-overridable via ``--source pico-sdk=<path>`` / ``--source
  cmsis-svd=<path-to-svd>``).
* Call the CMSIS-SVD parser to extract peripherals + interrupts
  + register layout.
* Stamp `provenance.source_id = "pico-sdk"`.

What it does NOT do yet (planned in Phase 1.5 follow-up):
* Apply RP2040 patch overlays (clock-tree edges, peripheral
  errata) — those still live codegen-side.
* Layer single-core-perspective bring-up descriptors.
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
    """Resolve the RP2040 SVD path from the request's source paths.

    * ``source_paths["cmsis-svd"]`` — direct path.
    * ``source_paths["pico-sdk"]`` — root of the pico-sdk
      checkout; we reach into ``src/rp2040/hardware_regs/RP2040.svd``.
    """
    if "cmsis-svd" in request.source_paths:
        return request.source_paths["cmsis-svd"]
    if "pico-sdk" in request.source_paths:
        candidate = (
            request.source_paths["pico-sdk"]
            / "src"
            / "rp2040"
            / "hardware_regs"
            / "RP2040.svd"
        )
        if candidate.exists():
            return candidate
    return None


@register_extractor(
    "pico-sdk",
    families=(("raspberrypi", "rp2040"),),
)
class PicoSdkExtractor:
    """RP2040 extractor — Phase 1.5 implementation."""

    extractor_id: str = "pico-sdk"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        svd_path = _resolve_svd_path(request)
        if svd_path is None or not svd_path.exists():
            available_keys = sorted(request.source_paths)
            raise ValueError(
                f"pico-sdk extractor: cannot resolve RP2040 SVD for "
                f"{request.device}.  Pass --source cmsis-svd=<path-to-svd> "
                f"or --source pico-sdk=<pico-sdk-checkout-root>.  "
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
        provenance["source_id"] = "pico-sdk"
        provenance["source_path"] = str(svd_path)
        payload["provenance"] = provenance

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="pico-sdk",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=(
                "RP2040 extractor: clock-tree + single-core "
                "bring-up descriptors not yet emitted — "
                "Phase 1.5 follow-up.",
            ),
        )


__all__ = ["PicoSdkExtractor"]
