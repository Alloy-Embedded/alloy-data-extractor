"""Bulk discovery + extraction.

`add-bulk-discovery-cmsis-pack-manager` (Phase 2.1) gives the
extractor a way to enumerate every chip in a vendor's CMSIS-Pack
catalog, dispatch each through its registered Extractor, and
write one canonical YAML per chip into alloy-devices-yml — all
in one CLI invocation.

Public surface:

* :class:`BulkChipRow` — one ``(vendor, family, device,
  source_paths, extractor_id)`` row.
* :class:`BulkRunSummary` — aggregate result of one bulk run.
* :func:`enumerate_pack_manager_chips(...)` — discovery via
  ``cmsis-pack-manager``.  Returns an iterator of
  :class:`BulkChipRow`.
* :func:`enumerate_local_packs(...)` — discovery via on-disk
  pack cache when cmsis-pack-manager isn't available offline.
* :func:`run_bulk(...)` — fan out + write YAMLs + return
  summary.
* :func:`shard_chips(...)` — deterministic partition for CI
  sharding.

Discovery is **deterministic**: same pinned packs → same chip
list, same order, same shards.

Per-chip failure isolation: one chip's `MissingSourceError` /
`ValueError` / `NotImplementedError` does not abort the run.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml
from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    Extractor,
    resolve_extractor,
)


@dataclass(frozen=True, slots=True)
class BulkChipRow:
    """One unit of work for the bulk runner."""

    vendor: str
    family: str
    device: str
    source_paths: dict[str, Path]


@dataclass(frozen=True, slots=True)
class BulkChipResult:
    """Outcome for one chip."""

    row: BulkChipRow
    status: str  # "PASS" | "EXTRACT_FAILED" | "NO_EXTRACTOR_REGISTERED" | "SCHEMA_INVALID"
    yaml_path: Path | None
    error: str | None


@dataclass(frozen=True, slots=True)
class BulkRunSummary:
    """Aggregate result of one bulk run."""

    results: tuple[BulkChipResult, ...]
    total: int
    passed: int
    failed: int
    skipped: int

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def to_report(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "status_counts": self.status_counts,
            "results": [
                {
                    "vendor": r.row.vendor,
                    "family": r.row.family,
                    "device": r.row.device,
                    "status": r.status,
                    "yaml_path": str(r.yaml_path) if r.yaml_path else None,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Discovery — cmsis-pack-manager (online) + local cache (offline)
# ---------------------------------------------------------------------------


_DEVICE_FILENAME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_+.-]*)\.(svd|atdf|xml)$", re.IGNORECASE)


def enumerate_local_packs(
    *,
    vendor: str,
    family: str,
    pack_root: Path,
    source_id: str,
    pattern: str = "**/*.svd",
) -> Iterator[BulkChipRow]:
    """Walk an on-disk pack root and yield one BulkChipRow per
    discovered file matching ``pattern``.  Device name comes
    from the filename stem.

    Used as the offline fallback when ``cmsis-pack-manager``
    isn't installed — and as the test-friendly discovery in CI
    fixtures.
    """
    for path in sorted(pack_root.glob(pattern)):
        match = _DEVICE_FILENAME_RE.match(path.name)
        if not match:
            continue
        device = match.group(1).lower()
        yield BulkChipRow(
            vendor=vendor,
            family=family,
            device=device,
            source_paths={source_id: path},
        )


def enumerate_pack_manager_chips(
    *,
    vendor: str,
    family: str,
    cache_dir: Path | None = None,
    filter_regex: str | None = None,
) -> Iterator[BulkChipRow]:
    """Enumerate every chip the cmsis-pack-manager catalog lists
    for ``vendor`` (case-insensitive prefix match on the
    catalog's vendor field).

    Requires ``cmsis-pack-manager`` to be installed and the
    pack catalog already downloaded (``cmsis-pack-manager
    update``).  Each yielded ``BulkChipRow`` carries the SVD
    path under ``source_paths["cmsis-svd"]``.
    """
    try:
        from cmsis_pack_manager import Cache  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "cmsis-pack-manager is not installed.  `pip install "
            "cmsis-pack-manager` or use enumerate_local_packs(...)."
        ) from exc

    cache = Cache(silent=True, no_refresh=True, data_path=cache_dir)
    if not cache.index:
        cache.cache_descriptors()
    pattern = re.compile(filter_regex) if filter_regex else None
    for device_name, info in sorted(cache.index.items()):
        info_vendor = (info.get("vendor") or "").split(":", 1)[0].lower()
        if vendor.lower() not in info_vendor:
            continue
        if pattern is not None and not pattern.search(device_name):
            continue
        svd_files = info.get("algorithms") or info.get("memories") or {}
        # cmsis-pack-manager exposes the SVD path under the
        # "compile" key (different keys across versions).
        svd_path: Path | None = None
        for key in ("svd", "from_pack", "compile"):
            candidate = info.get(key)
            if isinstance(candidate, str) and candidate.endswith(".svd"):
                svd_path = Path(candidate)
                break
            if isinstance(candidate, dict):
                hdr = candidate.get("header") or candidate.get("svd")
                if isinstance(hdr, str) and hdr.endswith(".svd"):
                    svd_path = Path(hdr)
                    break
        del svd_files  # keep linters quiet — present for future fields
        if svd_path is None:
            continue
        yield BulkChipRow(
            vendor=vendor,
            family=family,
            device=device_name.lower(),
            source_paths={"cmsis-svd": svd_path},
        )


# ---------------------------------------------------------------------------
# Sharding (deterministic by stable hash of (vendor, family, device))
# ---------------------------------------------------------------------------


def _stable_shard(vendor: str, family: str, device: str, total_shards: int) -> int:
    digest = hashlib.sha256(f"{vendor}/{family}/{device}".encode()).hexdigest()
    return int(digest[:8], 16) % total_shards


def shard_chips(
    chips: Iterable[BulkChipRow],
    *,
    shard: int,
    total_shards: int,
) -> Iterator[BulkChipRow]:
    """Filter ``chips`` to the Nth of M deterministic shards.

    Partition is exhaustive (no chip dropped) and disjoint (no
    chip duplicated).  Same chip set + same total_shards → same
    partition every run.
    """
    if total_shards < 1:
        raise ValueError(f"total_shards must be >= 1; got {total_shards}")
    if shard < 1 or shard > total_shards:
        raise ValueError(f"shard must be in 1..{total_shards}; got {shard}")
    for chip in chips:
        if _stable_shard(chip.vendor, chip.family, chip.device, total_shards) == shard - 1:
            yield chip


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _resolve_or_none(vendor: str, family: str) -> Extractor | None:
    try:
        return resolve_extractor(vendor, family)
    except ValueError:
        return None


def run_bulk(
    *,
    chips: Iterable[BulkChipRow],
    output_root: Path,
    revision: str,
    schema_path: Path | None = None,
    dry_run: bool = False,
) -> BulkRunSummary:
    """Fan out across chips, write YAMLs, return a structured
    summary.  Per-chip failures are isolated — they appear as
    ``EXTRACT_FAILED`` entries instead of aborting the run.
    """
    results: list[BulkChipResult] = []
    for chip in chips:
        extractor = _resolve_or_none(chip.vendor, chip.family)
        if extractor is None:
            results.append(
                BulkChipResult(
                    row=chip,
                    status="NO_EXTRACTOR_REGISTERED",
                    yaml_path=None,
                    error=f"no extractor registered for ({chip.vendor!r}, {chip.family!r})",
                )
            )
            continue
        if dry_run:
            results.append(
                BulkChipResult(
                    row=chip,
                    status="PASS",
                    yaml_path=None,
                    error=None,
                )
            )
            continue
        request = ExtractionRequest(
            vendor=chip.vendor,
            family=chip.family,
            device=chip.device,
            source_paths=chip.source_paths,
            revision=revision,
        )
        try:
            extraction = extractor.extract(request)
        except Exception as exc:  # noqa: BLE001
            results.append(
                BulkChipResult(
                    row=chip,
                    status="EXTRACT_FAILED",
                    yaml_path=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        try:
            yaml_path = write_device_yaml(
                payload=extraction.payload,
                output_root=output_root,
                vendor=chip.vendor,
                family=chip.family,
                device=chip.device,
                schema_path=schema_path,
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                BulkChipResult(
                    row=chip,
                    status="SCHEMA_INVALID",
                    yaml_path=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        results.append(
            BulkChipResult(
                row=chip,
                status="PASS",
                yaml_path=yaml_path,
                error=None,
            )
        )

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status not in ("PASS", "NO_EXTRACTOR_REGISTERED"))
    skipped = sum(1 for r in results if r.status == "NO_EXTRACTOR_REGISTERED")
    return BulkRunSummary(
        results=tuple(results),
        total=len(results),
        passed=passed,
        failed=failed,
        skipped=skipped,
    )


def write_bulk_report(summary: BulkRunSummary, *, path: Path) -> Path:
    """Write a JSON report of the bulk run."""
    path.write_text(json.dumps(summary.to_report(), indent=2, sort_keys=True), encoding="utf-8")
    return path


__all__ = [
    "BulkChipResult",
    "BulkChipRow",
    "BulkRunSummary",
    "enumerate_local_packs",
    "enumerate_pack_manager_chips",
    "run_bulk",
    "shard_chips",
    "write_bulk_report",
]
