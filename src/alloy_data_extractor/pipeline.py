"""High-level extraction pipeline orchestrator.

Dispatches per ``(vendor, family)`` through the protocol-level
registry from :mod:`alloy_data_extractor.extractor_protocol`.
No per-vendor ``if`` cascade — adding a new extractor is one
``@register_extractor(...)`` decorator on a class implementing
the :class:`Extractor` Protocol.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml

# Side-effect import: registers cmsis-svd + zephyr-dts in the
# protocol's _REGISTRY at module-import time.
from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    registered_extractor_ids,
    resolve_extractor,
    resolve_extractor_by_id,
)
from alloy_data_extractor.extractors import cmsis_pack as _cmsis_pack  # noqa: F401
from alloy_data_extractor.extractors import cmsis_svd as _cmsis_svd  # noqa: F401
from alloy_data_extractor.extractors import datasheet_pdf as _datasheet_pdf  # noqa: F401
from alloy_data_extractor.extractors import esp_idf as _esp_idf  # noqa: F401
from alloy_data_extractor.extractors import intel_8051 as _intel_8051  # noqa: F401
from alloy_data_extractor.extractors import microchip_dfp as _microchip_dfp  # noqa: F401
from alloy_data_extractor.extractors import microchip_pic as _microchip_pic  # noqa: F401
from alloy_data_extractor.extractors import modm_devices as _modm_devices  # noqa: F401
from alloy_data_extractor.extractors import msp430 as _msp430  # noqa: F401
from alloy_data_extractor.extractors import nxp_mcux as _nxp_mcux  # noqa: F401
from alloy_data_extractor.extractors import rp2040 as _rp2040  # noqa: F401
from alloy_data_extractor.extractors import stm32 as _stm32  # noqa: F401
from alloy_data_extractor.extractors import stm32_cubemx as _stm32_cubemx  # noqa: F401
from alloy_data_extractor.extractors import stm32_tier as _stm32_tier  # noqa: F401
from alloy_data_extractor.extractors import (
    stm32_open_pin_data as _stm32_open_pin_data,  # noqa: F401
)
from alloy_data_extractor.extractors import zephyr_dts as _zephyr_dts  # noqa: F401


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Per-device outcome of one ETL run.

    Pipeline-level result (file written + bytes), distinct
    from :class:`extractor_protocol.ExtractionResult`
    (in-memory payload + provenance).
    """

    vendor: str
    family: str
    device: str
    yaml_path: Path
    bytes_written: int
    provenance: dict[str, str]


def run_extraction(
    *,
    vendor: str,
    family: str,
    devices: Iterable[str],
    source_paths: dict[str, Path],
    output_root: Path,
    revision: str,
    extractor_id: str | None = None,
    schema_path: Path | None = None,
) -> tuple[ExtractionResult, ...]:
    """Run extraction for a list of devices.

    When ``extractor_id`` is None, auto-resolves from
    ``(vendor, family)`` via the registry.  Pass an explicit id
    when more than one extractor admits the pair.

    ``source_paths`` accepts two shapes for backward-compat:

    * ``{device_name: path}`` — legacy.  The path flows in
      under the resolved extractor's id.
    * ``{source_id: path}`` — preferred.  Direct mapping into
      :class:`ExtractionRequest.source_paths`.
    """
    if extractor_id is None:
        extractor = resolve_extractor(vendor, family)
    else:
        extractor = resolve_extractor_by_id(extractor_id)

    results: list[ExtractionResult] = []
    for device in devices:
        per_device_source = source_paths.get(device)
        if per_device_source is None:
            request_source_paths: dict[str, Path] = dict(source_paths)
        else:
            request_source_paths = {extractor.extractor_id: per_device_source}
        request = ExtractionRequest(
            vendor=vendor,
            family=family,
            device=device,
            source_paths=request_source_paths,
            revision=revision,
        )
        extraction = extractor.extract(request)
        out_path = write_device_yaml(
            payload=extraction.payload,
            output_root=output_root,
            vendor=vendor,
            family=family,
            device=device,
            schema_path=schema_path,
        )
        results.append(
            ExtractionResult(
                vendor=vendor,
                family=family,
                device=device,
                yaml_path=out_path,
                bytes_written=out_path.stat().st_size,
                provenance={
                    "source_id": extraction.provenance.source_id,
                    "revision": extraction.provenance.revision,
                    "source_path": str(extraction.provenance.source_path or ""),
                },
            )
        )
    return tuple(results)


def registered_extractors() -> tuple[str, ...]:
    """Return the IDs of every registered extractor.  Backward-
    compat shim for callers expecting the pre-protocol API.
    """
    return registered_extractor_ids()


def default_output_root() -> Path:
    """Best-effort guess at the alloy-devices-yml checkout location."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "alloy-devices-yml"
        if candidate.exists():
            return candidate
    return Path.cwd() / "alloy-devices-yml"


def _typecheck() -> dict[str, Any]:  # pragma: no cover
    return {"results": []}


__all__ = [
    "ExtractionResult",
    "default_output_root",
    "registered_extractors",
    "run_extraction",
]
