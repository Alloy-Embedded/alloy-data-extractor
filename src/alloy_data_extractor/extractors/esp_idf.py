"""Espressif ESP-IDF extractor — `migrate-espressif-esp-idf-extractor`
(Phase 1.4).

Reads the per-chip SVDs from `espressif-svd` / esp-idf.  The
SVDs are well-known partial documents: ESP32 register coverage
of UART1/UART2/SPI2/SPI3/I2C1/TIMG1 is incomplete upstream.
Codegen-side patches fill those gaps; the extractor faithfully
projects whatever the SVD ships.

What this DOES today:
* Resolve the SVD path from the ``espressif-svd`` source root
  (one ``svd/<chip>.svd`` per family) or directly from
  ``--source cmsis-svd=<path>``.
* Extract peripherals + interrupts + register layout via the
  CMSIS-SVD parser.

What it does NOT do yet:
* Layer the dual-core control-plane facts (PRO_CPU + APP_CPU
  bring-up descriptors).
* Apply the manual DPORT clock-gate patches.
* Codegen-side patches still apply per the legacy path.
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

_FAMILY_TO_SVD = {
    "esp32": "esp32.svd",
    "esp32c3": "esp32c3.svd",
    "esp32s3": "esp32s3.svd",
}


# Per-family core fallback — ESP32 SVDs don't carry a `<cpu>`
# element (Espressif uses Xtensa LX6/LX7 + RISC-V variants
# that aren't part of the CMSIS-SVD CPU vocabulary).
_FAMILY_TO_CORE = {
    "esp32": "xtensa-lx6",
    "esp32s2": "xtensa-lx7",
    "esp32s3": "xtensa-lx7",
    "esp32c2": "riscv-rv32imc",
    "esp32c3": "riscv-rv32imc",
    "esp32c6": "riscv-rv32imac",
    "esp32h2": "riscv-rv32imac",
    "esp32p4": "riscv-rv32imafc",
}


def _resolve_svd_path(request: ExtractionRequest) -> Path | None:
    if "cmsis-svd" in request.source_paths:
        return request.source_paths["cmsis-svd"]
    if "espressif-svd" in request.source_paths:
        filename = _FAMILY_TO_SVD.get(request.family)
        if filename is None:
            return None
        candidate = request.source_paths["espressif-svd"] / "svd" / filename
        if candidate.exists():
            return candidate
    return None


@register_extractor(
    "esp-idf",
    families=tuple(("espressif", fam) for fam in _FAMILY_TO_CORE),
)
class EspIdfExtractor:
    """Espressif ESP-IDF extractor — Phase 1.4 implementation."""

    extractor_id: str = "esp-idf"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        svd_path = _resolve_svd_path(request)
        if svd_path is None or not svd_path.exists():
            available_keys = sorted(request.source_paths)
            raise ValueError(
                f"esp-idf extractor: cannot resolve SVD for "
                f"{request.family}/{request.device}.  Pass "
                f"--source cmsis-svd=<path> or "
                f"--source espressif-svd=<espressif-svd-checkout>.  "
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
        provenance["source_id"] = "esp-idf"
        provenance["source_path"] = str(svd_path)
        payload["provenance"] = provenance

        # Per-family core fallback — ESP32 SVDs don't carry a
        # CMSIS-SVD-style <cpu> element (Xtensa / RISC-V variants).
        identity = dict(payload.get("identity", {}))
        if not identity.get("core"):
            fallback = _FAMILY_TO_CORE.get(request.family)
            if fallback:
                identity["core"] = fallback
                payload["identity"] = identity

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="esp-idf",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=(
                "ESP-IDF extractor: dual-core control plane + "
                "DPORT clock-gate patches not yet emitted — "
                "Phase 1.4 follow-up.",
            ),
        )


__all__ = ["EspIdfExtractor"]
