"""CMSIS-Pack-Manager-backed bulk discovery + extraction.

Wraps the cmsis-pack-manager Python API to:

* Enumerate every chip in the global CMSIS-Pack catalog
  (~11,000 devices across ARM Cortex-M, Cortex-A, Cortex-R).
* Download per-vendor pack files (`.pack` = ZIP archives) on
  demand.
* Extract SVD files from those packs and run the existing
  CMSIS-SVD extractor against them.

Public surface:

* :func:`load_catalog(refresh=False)` — return the cached
  ``Cache`` instance with its index populated.
* :func:`enumerate_catalog_chips(vendor_substring=None,
  family_substring=None, filter_regex=None)` — yield
  :class:`CatalogChip` records for chips matching the filter.
* :func:`prepare_pack_for_chip(cache, device_record)` —
  download the chip's pack if not yet cached and return the
  extracted SVD path.
* :class:`CmsisPackBulkExtractor` — :class:`Extractor`
  protocol adapter that resolves the chip in the catalog,
  prepares its pack, and dispatches to the CMSIS-SVD reader.

This is the backbone of `add-bulk-discovery-cmsis-pack-manager`
(Phase 2.1) end-to-end: discover → download → extract.

Network access is required for the first run; subsequent runs
re-use the local pack cache (default
``~/Library/Application Support/cmsis-pack-manager/`` on macOS;
elsewhere ``~/.cache/cmsis-pack-manager/``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)
from alloy_data_extractor.extractors.cmsis_svd import extract_device as _cmsis_svd_extract

# Map cmsis-pack-manager's CPU strings to alloy canonical core
# values.  The shape comes from `<processor core="...">` in
# the per-chip pdsc record.
_CMSIS_PACK_CORE_TO_ALLOY: dict[str, str] = {
    "CortexM0": "cortex-m0",
    "CortexM0Plus": "cortex-m0plus",
    "CortexM1": "cortex-m1",
    "CortexM3": "cortex-m3",
    "CortexM4": "cortex-m4",
    "CortexM4f": "cortex-m4f",
    "CortexM7": "cortex-m7",
    "CortexM7f": "cortex-m7f",
    "CortexM23": "cortex-m23",
    "CortexM33": "cortex-m33",
    "CortexM35P": "cortex-m35p",
    "CortexM55": "cortex-m55",
    "CortexA5": "cortex-a5",
    "CortexA7": "cortex-a7",
    "CortexA9": "cortex-a9",
    "CortexR4": "cortex-r4",
    "CortexR5": "cortex-r5",
}


@dataclass(frozen=True, slots=True)
class CatalogChip:
    """One row of the CMSIS-Pack catalog."""

    name: str  # e.g. "STM32G071C8Tx"
    vendor: str  # e.g. "STMicroelectronics:13" — keep the raw form
    vendor_short: str  # e.g. "stmicroelectronics" (no `:N` suffix)
    family: str  # e.g. "STM32G0 Series"
    sub_family: str  # e.g. "STM32G071"
    core: str  # alloy canonical, e.g. "cortex-m0plus"
    raw: dict[str, Any]


def _alloy_core_for_record(record: dict[str, Any]) -> str:
    procs = record.get("processors") or []
    if isinstance(procs, list) and procs:
        first = procs[0]
        if isinstance(first, dict):
            core_raw = first.get("core")
            fpu = (first.get("fpu") or "None")
            if isinstance(core_raw, str):
                # Synthesize Cortex-M4f / M7f when the FPU
                # field signals one — vendor records often use
                # plain `CortexM4` even with hardware FPU.
                if core_raw in {"CortexM4", "CortexM7"} and fpu and fpu.lower() not in ("none", ""):
                    return _CMSIS_PACK_CORE_TO_ALLOY.get(core_raw + "f", core_raw.lower())
                return _CMSIS_PACK_CORE_TO_ALLOY.get(core_raw, core_raw.lower())
    return ""


def _alloy_vendor_for_record(record: dict[str, Any]) -> str:
    raw_vendor = record.get("vendor") or ""
    short = str(raw_vendor).split(":", 1)[0].strip().lower()
    # Common vendor-name aliases → alloy short keys.
    aliases = {
        "stmicroelectronics": "st",
        "raspberrypi": "raspberrypi",
        "raspberry": "raspberrypi",
        "espressif": "espressif",
        "espressif systems": "espressif",
        "nordicsemiconductor": "nordic",
        "nordic semiconductor": "nordic",
        "microchip": "microchip",
        "atmel": "atmel",
        "nxp": "nxp",
        "renesas electronics": "renesas",
        "texasinstruments": "ti",
        "texas instruments": "ti",
        "infineon technologies": "infineon",
        "silicon labs": "silabs",
        "silicon laboratories": "silabs",
        "ambiq micro": "ambiq",
        "gigadevice": "gigadevice",
        "wch": "wch",
    }
    return aliases.get(short, short)


def load_catalog(refresh: bool = False, *, data_path: Path | None = None) -> Any:
    """Return a populated cmsis-pack-manager ``Cache``.

    When ``refresh`` is True we re-download the vendor index
    (vidx) before returning; otherwise we use whatever was last
    cached on disk.  Falls back to running ``cache_descriptors``
    when the local cache is empty.
    """
    from cmsis_pack_manager import Cache  # type: ignore[import-not-found]

    cache = Cache(True, False, data_path=str(data_path) if data_path else None)
    if refresh or not cache.index:
        cache.cache_descriptors()
    return cache


def enumerate_catalog_chips(
    cache: Any,
    *,
    vendor_substring: str | None = None,
    family_substring: str | None = None,
    filter_regex: str | None = None,
) -> Iterator[CatalogChip]:
    """Yield every chip in the catalog matching the filters."""
    pattern = re.compile(filter_regex) if filter_regex else None
    for name, record in sorted(cache.index.items()):
        if not isinstance(record, dict):
            continue
        record_vendor = str(record.get("vendor", "")).lower()
        record_family = str(record.get("family", "")).lower()
        if vendor_substring and vendor_substring.lower() not in record_vendor:
            continue
        if family_substring and family_substring.lower() not in record_family:
            continue
        if pattern is not None and not pattern.search(name):
            continue
        yield CatalogChip(
            name=name,
            vendor=str(record.get("vendor", "")),
            vendor_short=_alloy_vendor_for_record(record),
            family=str(record.get("family", "")),
            sub_family=str(record.get("sub_family", "")),
            core=_alloy_core_for_record(record),
            raw=record,
        )


def prepare_pack_for_chip(cache: Any, device_record: dict[str, Any]) -> Path | None:
    """Make sure the chip's pack is on disk; return the pack path
    or ``None`` if pack download / cache lookup fails."""
    refs = cache.packs_for_devices([device_record])
    if not refs:
        return None
    try:
        cache.download_pack_list(refs)
    except Exception:  # noqa: BLE001
        return None
    try:
        zf = cache.pack_from_cache(device_record)
    except Exception:  # noqa: BLE001
        return None
    return Path(zf.filename) if hasattr(zf, "filename") else None


def extract_svd_from_pack(pack_path: Path, chip_name: str, *, work_dir: Path) -> Path | None:
    """Extract one chip's SVD from a pack zipfile and return
    the unpacked path.

    Strategy: prefer an SVD whose stem matches the chip name
    prefix (e.g. ``STM32G071`` for ``STM32G071C8Tx``); fall back
    to any SVD in the pack.
    """
    import zipfile

    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pack_path) as zf:
        svd_paths = [n for n in zf.namelist() if n.lower().endswith(".svd")]
        if not svd_paths:
            return None
        # Pick the longest-prefix match.
        upper = chip_name.upper()
        scored = sorted(
            svd_paths,
            key=lambda n: (
                -len(_common_prefix(Path(n).stem.upper(), upper)),
                n,
            ),
        )
        chosen = scored[0]
        out = work_dir / Path(chosen).name
        if not out.exists():
            with zf.open(chosen) as src, out.open("wb") as dst:
                dst.write(src.read())
        return out


def _common_prefix(a: str, b: str) -> str:
    out: list[str] = []
    for c1, c2 in zip(a, b, strict=False):
        if c1 != c2:
            break
        out.append(c1)
    return "".join(out)


# ---------------------------------------------------------------------------
# Extractor protocol adapter
# ---------------------------------------------------------------------------


@register_extractor(
    "cmsis-pack",
    # Synthetic family — use cmsis-pack-manager via explicit
    # `--source cmsis-pack=<chip-name>` invocation, not auto-resolution.
    families=(("__cmsis_pack_secondary__", "__cmsis_pack_secondary__"),),
)
class CmsisPackBulkExtractor:
    """Pull a chip from the global CMSIS-Pack catalog."""

    extractor_id: str = "cmsis-pack"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        # The chip is identified by the request's `device` (which
        # we pass case-insensitively into the catalog lookup).
        cache = load_catalog(refresh=False)
        chip_name = request.device.upper() if request.device else ""
        if chip_name not in cache.index:
            # Try `STM32G071C8Tx` ↔ `stm32g071c8tx` matching.
            for candidate in cache.index:
                if candidate.upper() == chip_name.upper():
                    chip_name = candidate
                    break
            else:
                raise ValueError(
                    f"cmsis-pack extractor: chip {request.device!r} not in "
                    f"the CMSIS-Pack catalog (catalog size: {len(cache.index)})."
                )
        record = cache.index[chip_name]

        pack_path = prepare_pack_for_chip(cache, record)
        if pack_path is None:
            raise ValueError(
                f"cmsis-pack extractor: failed to prepare pack for {chip_name!r}."
            )
        work_dir = Path(pack_path).parent / "_alloy_extracted"
        svd_path = extract_svd_from_pack(pack_path, chip_name, work_dir=work_dir)
        if svd_path is None:
            raise ValueError(
                f"cmsis-pack extractor: pack for {chip_name!r} contains no SVD file."
            )

        # Reuse the CMSIS-SVD extractor for the heavy lifting.
        legacy = _cmsis_svd_extract(
            vendor=_alloy_vendor_for_record(record),
            family=request.family,
            device=request.device,
            svd_path=svd_path,
            revision=request.revision,
        )
        # Layer in the catalog metadata.  CMSIS-Pack `processors`
        # is the authoritative source for the CPU+FPU+MPU shape;
        # SVD-derived `core` is sometimes coarser (STM32G0 SVDs
        # name themselves "CM0" even though they're Cortex-M0+).
        payload = dict(legacy.payload)
        identity = dict(payload.get("identity", {}))
        identity["vendor"] = _alloy_vendor_for_record(record)
        catalog_core = _alloy_core_for_record(record)
        if catalog_core:
            identity["core"] = catalog_core
        if not identity.get("summary"):
            identity["summary"] = (
                f"{record.get('sub_family', '')} ({record.get('family', '')})".strip()
            )
        payload["identity"] = identity

        # Memories: pull flash + sram regions from the catalog
        # record's `memories` block.  Kind classification uses
        # name heuristics + the access bits CMSIS-Pack provides
        # (rom is read-only-execute; ram is read-write).
        memories: list[dict[str, Any]] = []
        for name, info in (record.get("memories") or {}).items():
            try:
                lower_name = str(name).lower()
                access = info.get("access", {}) if isinstance(info, dict) else {}
                is_writable = bool(access.get("write"))
                is_executable = bool(access.get("execute"))
                if "flash" in lower_name or "rom" in lower_name:
                    kind = "flash"
                elif "ram" in lower_name:
                    kind = "sram"
                elif is_executable and not is_writable:
                    # Cortex-M flash region by capability.
                    kind = "flash"
                elif is_writable and is_executable:
                    kind = "sram"
                else:
                    kind = "memory"
                # Access string follows the alloy convention: r/w/x.
                access_chars = ""
                if access.get("read"):
                    access_chars += "r"
                if is_writable:
                    access_chars += "w"
                if is_executable:
                    access_chars += "x"
                memories.append(
                    {
                        "name": lower_name,
                        "kind": kind,
                        "base_address": int(info.get("start", 0)),
                        "size_bytes": int(info.get("size", 0)),
                        "access": access_chars or "rw",
                    }
                )
            except (TypeError, ValueError):
                continue
        if memories:
            payload["memories"] = memories

        # Stamp provenance.
        provenance = dict(payload.get("provenance", {}))
        provenance["source_id"] = "cmsis-pack"
        provenance["source_path"] = str(svd_path)
        from_pack = record.get("from_pack") or {}
        if isinstance(from_pack, dict):
            provenance["pack_vendor"] = from_pack.get("vendor", "")
            provenance["pack_name"] = from_pack.get("pack", "")
            provenance["pack_version"] = from_pack.get("version", "")
        payload["provenance"] = provenance

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="cmsis-pack",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=(
                "cmsis-pack extractor: register-tree depth depends on the "
                "vendor's pack — some packs ship abbreviated SVDs.",
            ),
        )


__all__ = [
    "CatalogChip",
    "CmsisPackBulkExtractor",
    "enumerate_catalog_chips",
    "extract_svd_from_pack",
    "load_catalog",
    "prepare_pack_for_chip",
]
