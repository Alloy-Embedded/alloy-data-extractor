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


# Per-family default core, used when the SVD's <cpu> element is
# missing or names a CPU the cmsis-svd extractor's table doesn't
# resolve (some ST SVDs are sparse on CPU metadata).
_FAMILY_TO_CORE = {
    "stm32f0": "cortex-m0",
    "stm32f1": "cortex-m3",
    "stm32f2": "cortex-m3",
    "stm32f3": "cortex-m4f",
    "stm32f4": "cortex-m4f",
    "stm32f7": "cortex-m7f",
    "stm32g0": "cortex-m0plus",
    "stm32g4": "cortex-m4f",
    "stm32h7": "cortex-m7f",
    "stm32l0": "cortex-m0plus",
    "stm32l1": "cortex-m3",
    "stm32l4": "cortex-m4f",
    "stm32l5": "cortex-m33",
    "stm32u0": "cortex-m0plus",
    "stm32u5": "cortex-m33",
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
    families=tuple(("st", fam) for fam in _FAMILY_TO_CORE),
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
        # extractions from generic CMSIS-SVD ones — both at the
        # top level and on every per-row provenance block stamped
        # by `_peripheral_records` / `_register_and_field_records`.
        # Top-level source_path uses the SVD basename so the
        # YAMLs are environment-stable (same convention as
        # canonical alloy-devices-yml + as the per-row prov).
        payload = dict(legacy.payload)
        provenance = dict(payload.get("provenance", {}))
        provenance["source_id"] = "stm32"
        provenance["source_path"] = svd_path.name
        payload["provenance"] = provenance
        for row_field in ("peripherals", "interrupts", "registers", "register_fields"):
            rows = payload.get(row_field, [])
            for row in rows:
                row_prov = row.get("provenance")
                if isinstance(row_prov, dict):
                    row_prov["source_id"] = "stm32"

        # Per-family core override: STM32 SVDs in cmsis-svd-data
        # ship with stale CPU info — STM32G071's SVD declares
        # `<name>CM0</name>` despite the chip being a Cortex-M0+
        # part.  The curated `_FAMILY_TO_CORE` table is the
        # authoritative answer per ST's reference manuals; let it
        # win over whatever the SVD declares.
        identity = dict(payload.get("identity", {}))
        family_core = _FAMILY_TO_CORE.get(request.family)
        if family_core:
            identity["core"] = family_core
        elif not identity.get("core"):
            identity["core"] = ""

        # Optional package lookup from CubeMX MCU XML when the
        # `stm32cubemx-db` source is staged alongside the SVD.
        # The CubeMX `<Mcu Package="LQFP64">` attribute is the
        # canonical answer.  The primary path doesn't *require*
        # CubeMX; package falls through to "" when absent.
        if "stm32cubemx-db" in request.source_paths:
            try:
                from alloy_data_extractor.extractors.stm32_cubemx import (
                    _find_db_root,
                    _match_mcu_xml,
                    _parse_mcu_xml,
                )

                supplied = request.source_paths["stm32cubemx-db"]
                roots = _find_db_root(supplied)
                if roots is not None:
                    mcu_root, _ = roots
                    mcu_xml = _match_mcu_xml(mcu_root, request.device)
                    if mcu_xml is not None:
                        facts = _parse_mcu_xml(mcu_xml)
                        if facts.package:
                            identity["package"] = facts.package
            except Exception:  # noqa: BLE001
                # Best-effort enrichment — never fail the primary
                # extraction because CubeMX lookup misbehaved.
                pass

        if identity.get("package") is None:
            identity["package"] = ""
        payload["identity"] = identity

        warnings: list[str] = []
        if not payload.get("registers"):
            warnings.append(
                "STM32 extractor: SVD carried no register tree — "
                "merged YAMLs will lack `registers` / `register_fields`."
            )
        if not payload.get("pins"):
            warnings.append(
                "STM32 extractor: pinmux / AF tables not emitted by the "
                "primary path — compose with stm32-cubemx via the merge "
                "engine to populate `pins` / `dma_requests`."
            )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="stm32",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = ["Stm32Extractor"]
