"""Catalog index for alloy-devices-yml.

`add-coverage-index-and-dashboard` (Phase 2.3 of the roadmap)
walks `vendors/**/devices/*.yml` and builds a single
``index.yml`` describing every admitted (vendor, family, device)
triple along with its `schema_version`, `provenance.source_id`,
`provenance.revision`, and the file's ``extracted_at``
timestamp.

Public surface:

* :func:`build_index(data_repo_root)` — walk + build an
  in-memory :class:`CatalogIndex`.
* :func:`serialize_index(index)` — render canonical YAML.
* :func:`write_index(...)` — drop ``index.yml`` at the data
  repo root.
* :func:`is_index_stale(...)` — predicate the alloy-devices-yml
  CI gate checks: True if the on-disk ``index.yml`` does not
  match the recomputed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One row in the catalog — the per-device summary."""

    vendor: str
    family: str
    device: str
    schema_version: str
    source_id: str
    revision: str
    yaml_path: str  # repo-relative


@dataclass(frozen=True, slots=True)
class CatalogIndex:
    """Catalog of every committed device YAML.

    Sorted lexicographically by (vendor, family, device) so the
    serialised form is deterministic across rebuilds.
    """

    entries: tuple[CatalogEntry, ...]
    total_devices: int
    vendor_count: int
    family_count: int
    schema_versions: tuple[str, ...]


def _entry_from_yaml(yaml_path: Path, repo_root: Path) -> CatalogEntry | None:
    """Parse one YAML into a :class:`CatalogEntry`.  Returns
    ``None`` when the YAML lacks required identity fields."""
    try:
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(payload, dict):
        return None
    identity = payload.get("identity", {}) or {}
    vendor = identity.get("vendor")
    family = identity.get("family")
    device = identity.get("device")
    if not (vendor and family and device):
        return None
    provenance = payload.get("provenance", {}) or {}
    return CatalogEntry(
        vendor=str(vendor),
        family=str(family),
        device=str(device),
        schema_version=str(payload.get("schema_version", "unknown")),
        source_id=str(provenance.get("source_id", "unknown")),
        revision=str(provenance.get("revision", "unknown")),
        yaml_path=str(yaml_path.relative_to(repo_root)).replace("\\", "/"),
    )


def build_index(data_repo_root: Path) -> CatalogIndex:
    """Walk ``vendors/**/devices/*.yml`` and build the index."""
    entries: list[CatalogEntry] = []
    for yaml_path in sorted((data_repo_root / "vendors").glob("**/devices/*.yml")):
        entry = _entry_from_yaml(yaml_path, data_repo_root)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda e: (e.vendor, e.family, e.device))
    return CatalogIndex(
        entries=tuple(entries),
        total_devices=len(entries),
        vendor_count=len({e.vendor for e in entries}),
        family_count=len({(e.vendor, e.family) for e in entries}),
        schema_versions=tuple(sorted({e.schema_version for e in entries})),
    )


def _index_to_payload(index: CatalogIndex) -> dict[str, Any]:
    """Serialisation-ready shape (preserves entry order)."""
    return {
        "schema_version": "1.0.0",
        "summary": {
            "total_devices": index.total_devices,
            "vendor_count": index.vendor_count,
            "family_count": index.family_count,
            "schema_versions": list(index.schema_versions),
        },
        "devices": [
            {
                "vendor": e.vendor,
                "family": e.family,
                "device": e.device,
                "schema_version": e.schema_version,
                "source_id": e.source_id,
                "revision": e.revision,
                "yaml_path": e.yaml_path,
            }
            for e in index.entries
        ],
    }


def serialize_index(index: CatalogIndex) -> str:
    """Render the index as deterministic YAML."""
    text = yaml.dump(
        _index_to_payload(index),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10_000,
    )
    if not text.endswith("\n"):
        text += "\n"
    return text


def write_index(*, data_repo_root: Path, index: CatalogIndex | None = None) -> Path:
    """Write ``index.yml`` at ``data_repo_root``.  If ``index`` is
    None, rebuilds from disk."""
    if index is None:
        index = build_index(data_repo_root)
    out_path = data_repo_root / "index.yml"
    out_path.write_text(serialize_index(index), encoding="utf-8")
    return out_path


def is_index_stale(*, data_repo_root: Path) -> tuple[bool, str]:
    """Return ``(is_stale, message)``.

    True when:

    * ``index.yml`` does not exist.
    * Its content does not match the freshly-built index.
    """
    on_disk = data_repo_root / "index.yml"
    if not on_disk.exists():
        return True, "index.yml is missing — run `alloy-data-extract index`."
    fresh = serialize_index(build_index(data_repo_root))
    current = on_disk.read_text(encoding="utf-8")
    if fresh == current:
        return False, "index.yml is up to date."
    return True, (
        "index.yml is stale — re-run `alloy-data-extract index` "
        "before committing."
    )


__all__ = [
    "CatalogEntry",
    "CatalogIndex",
    "build_index",
    "is_index_stale",
    "serialize_index",
    "write_index",
]
