"""STM32 extractor — `migrate-stm32-extractor` (Phase 1.1).

This is a transitional implementation: it reads CMSIS-SVD via
the existing :mod:`alloy_data_extractor.extractors.cmsis_svd`
adapter and produces a minimal-but-valid canonical YAML payload
for STM32 chips.

What this DOES today:
* Resolve the SVD path for an admitted STM32 device from a
  configured `cmsis-svd-data` source root (env-overridable).
* Call the CMSIS-SVD parser to extract peripherals + interrupts
  + register layout into the canonical payload shape.
* Stamp `provenance.source_id = "stm32"` so reviewers can
  distinguish STM32-extracted YAMLs from generic CMSIS-SVD ones.

What it does NOT do yet (planned in follow-ups):
* Read STM32_open_pin_data XML for pinmux/AF tables — that's a
  separate parser port, currently in
  ``alloy-codegen/src/alloy_codegen/sources/stm32_open_pin_data.py``.
  Until ported, STM32 YAMLs continue to come from the codegen
  legacy path (which the parity gate keeps green).
* Apply codegen-side device patches.
* Layer modm-devices enrichment (Phase 1.7 + 2.2).

The codegen pipeline still uses ``_build_st_device_ir`` until
the full port lands; this extractor is *additive* infrastructure
that downstream Phase-1 work fills in.
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

# Naming convention in cmsis-svd-data/data/STMicro/.  Most STM32
# chips share an SVD per series — e.g. STM32G071RB → STM32G07x.svd.
# The mapping is hand-curated for the admitted devices; bulk
# discovery (Phase 2.1) generalises it.
_DEVICE_TO_SVD = {
    "stm32g030f6": "STM32G030.svd",
    "stm32g071rb": "STM32G071.svd",
    "stm32g0b1re": "STM32G0B1.svd",
    "stm32f401re": "STM32F401.svd",
    "stm32f405rg": "STM32F405.svd",
}


def _resolve_svd_path(request: ExtractionRequest) -> Path | None:
    """Resolve the SVD path from the request's source paths.

    Accepts three shapes:

    * ``source_paths["cmsis-svd"]`` — direct path to the SVD.
    * ``source_paths["cmsis-svd-data"]`` — root of the
      cmsis-svd-data checkout; combined with the device → svd
      filename map.
    * ``source_paths["stm32"]`` — same as cmsis-svd-data.
    """
    if "cmsis-svd" in request.source_paths:
        return request.source_paths["cmsis-svd"]
    for key in ("stm32", "cmsis-svd-data"):
        if key in request.source_paths:
            root = request.source_paths[key]
            filename = _DEVICE_TO_SVD.get(request.device)
            if filename is None:
                return None
            candidate = root / "data" / "STMicro" / filename
            if candidate.exists():
                return candidate
    return None


@register_extractor(
    "stm32",
    families=(
        ("st", "stm32f4"),
        ("st", "stm32g0"),
    ),
)
class Stm32Extractor:
    """STM32 extractor — Phase 1.1 implementation."""

    extractor_id: str = "stm32"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False  # decorator-derived bindings handle admission

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        svd_path = _resolve_svd_path(request)
        if svd_path is None or not svd_path.exists():
            available_keys = sorted(request.source_paths)
            raise ValueError(
                f"stm32 extractor: cannot resolve SVD for "
                f"{request.vendor}/{request.family}/{request.device}.  "
                f"Pass --source cmsis-svd=<path-to-svd> or "
                f"--source stm32=<cmsis-svd-data-root>.  "
                f"Got source keys: {available_keys}"
            )
        legacy = _cmsis_svd_extract(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            svd_path=svd_path,
            revision=request.revision,
        )
        # Tag provenance so reviewers can distinguish STM32-specific
        # extractions from generic CMSIS-SVD ones.
        payload = dict(legacy.payload)
        provenance = dict(payload.get("provenance", {}))
        provenance["source_id"] = "stm32"
        provenance["source_path"] = str(svd_path)
        payload["provenance"] = provenance

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="stm32",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=(
                "STM32 extractor: pinmux / AF tables not yet emitted — "
                "Phase 1.1 follow-up ports STM32_open_pin_data.",
            ),
        )


__all__ = ["Stm32Extractor"]
