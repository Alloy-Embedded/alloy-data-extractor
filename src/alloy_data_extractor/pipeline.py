"""High-level extraction pipeline orchestrator.

Dispatches per ``(vendor, family)`` to the appropriate extractor,
runs it against the configured source, and writes the resulting
canonical YAML into ``alloy-devices-yml``.

For v1 the only registered extractor is ``cmsis_svd``.  Other
extractors (ATDF, MCUXpresso, Zephyr DTS, ESP-IDF, modm-data,
Pico SDK) migrate from alloy-codegen in incremental changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml
from alloy_data_extractor.extractors import cmsis_svd


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Per-device outcome of one ETL run."""

    vendor: str
    family: str
    device: str
    yaml_path: Path
    bytes_written: int
    provenance: dict[str, str]


# Registry: ``(vendor, family) -> extractor function``.  More
# entries land as additional extractors migrate over.
_EXTRACTORS = {
    "cmsis-svd": cmsis_svd,
}


def run_extraction(
    *,
    vendor: str,
    family: str,
    devices: Iterable[str],
    extractor_id: str,
    source_paths: dict[str, Path],
    output_root: Path,
    revision: str,
    schema_path: Path | None = None,
) -> tuple[ExtractionResult, ...]:
    """Run one extractor for a list of devices.

    ``extractor_id`` selects the extractor module by ID
    (e.g. ``"cmsis-svd"``).  ``source_paths`` maps each
    device-name → source file path (one SVD per device for the
    cmsis-svd extractor).
    """
    if extractor_id not in _EXTRACTORS:
        raise ValueError(f"unknown extractor_id {extractor_id!r}; known: {sorted(_EXTRACTORS)}")
    extractor = _EXTRACTORS[extractor_id]
    results: list[ExtractionResult] = []
    for device in devices:
        source_path = source_paths.get(device)
        if source_path is None:
            raise ValueError(f"no source path provided for device {device!r}")
        extraction = extractor.extract_device(
            vendor=vendor,
            family=family,
            device=device,
            svd_path=source_path,
            revision=revision,
        )
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
                provenance=extraction.provenance,
            )
        )
    return tuple(results)


def registered_extractors() -> tuple[str, ...]:
    """Return the IDs of every registered extractor — for CLI
    discovery and `--list-extractors` output."""
    return tuple(sorted(_EXTRACTORS))


__all__ = ["ExtractionResult", "registered_extractors", "run_extraction"]


# Resolve the output-root contract: default to a sibling
# ``alloy-devices-yml`` checkout.  Used by the CLI when
# ``--output-root`` is not supplied.
def default_output_root() -> Path:
    """Best-effort guess at the data-repo location."""
    here = Path(__file__).resolve()
    # repo-root / alloy-devices-yml siblings
    for parent in here.parents:
        candidate = parent / "alloy-devices-yml"
        if candidate.exists():
            return candidate
    return Path.cwd() / "alloy-devices-yml"


# Helper for the CLI to expose the data type it returns.
def _typecheck() -> dict[str, Any]:  # pragma: no cover
    return {"results": []}
