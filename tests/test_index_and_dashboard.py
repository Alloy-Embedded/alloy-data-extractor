"""Tests for `add-coverage-index-and-dashboard` (Phase 2.3):
the catalog index builder + dashboard renderer.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import yaml  # noqa: E402

from alloy_data_extractor.dashboard import render_dashboard  # noqa: E402
from alloy_data_extractor.index import (  # noqa: E402
    build_index,
    is_index_stale,
    serialize_index,
    write_index,
)


def _populate_repo(tmp_path: Path) -> Path:
    """Build a synthetic alloy-devices-yml-shaped tree."""
    devices = [
        ("st", "stm32g0", "stm32g071rb", "1.2.0", "stm32"),
        ("st", "stm32g0", "stm32g030f6", "1.2.0", "stm32"),
        ("st", "stm32f4", "stm32f401re", "1.2.0", "stm32"),
        ("nordic", "nrf52", "nrf52840", "1.2.0", "zephyr-dts"),
        ("microchip", "same70", "atsame70q21b", "1.2.0", "microchip-dfp"),
        ("nxp", "imxrt1060", "mimxrt1062", "1.2.1", "nxp-mcux"),
    ]
    for vendor, family, device, version, source_id in devices:
        target = tmp_path / "vendors" / vendor / family / "devices" / f"{device}.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            textwrap.dedent(f"""\
                schema_version: {version}
                identity:
                  vendor: {vendor}
                  family: {family}
                  device: {device}
                  core: cortex-m0
                provenance:
                  source_id: {source_id}
                  revision: rev-{device}
            """),
            encoding="utf-8",
        )
    return tmp_path


def test_build_index_walks_yaml_tree(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    index = build_index(repo)
    assert index.total_devices == 6
    assert index.vendor_count == 4
    assert index.family_count == 5
    assert "1.2.0" in index.schema_versions
    assert "1.2.1" in index.schema_versions

    triples = {(e.vendor, e.family, e.device) for e in index.entries}
    assert ("st", "stm32g0", "stm32g071rb") in triples
    assert ("nxp", "imxrt1060", "mimxrt1062") in triples


def test_index_serialisation_is_deterministic(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    a = serialize_index(build_index(repo))
    b = serialize_index(build_index(repo))
    assert a == b
    # Round-trip: parse the serialised form.
    parsed = yaml.safe_load(a)
    assert parsed["summary"]["total_devices"] == 6
    assert parsed["devices"][0]["vendor"]  # has at least one device row


def test_write_index_creates_file_at_root(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    out = write_index(data_repo_root=repo)
    assert out == repo / "index.yml"
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("schema_version: 1.0.0")


def test_is_index_stale_detects_missing(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    stale, msg = is_index_stale(data_repo_root=repo)
    assert stale is True
    assert "missing" in msg


def test_is_index_stale_detects_drift(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    write_index(data_repo_root=repo)
    # Add a new YAML without rebuilding the index.
    new_path = repo / "vendors" / "st" / "stm32g0" / "devices" / "stm32g070cb.yml"
    new_path.write_text(
        textwrap.dedent("""\
            schema_version: 1.2.0
            identity:
              vendor: st
              family: stm32g0
              device: stm32g070cb
              core: cortex-m0
            provenance:
              source_id: stm32
              revision: rev-x
        """),
        encoding="utf-8",
    )
    stale, msg = is_index_stale(data_repo_root=repo)
    assert stale is True
    assert "stale" in msg


def test_is_index_stale_detects_freshness(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    write_index(data_repo_root=repo)
    stale, msg = is_index_stale(data_repo_root=repo)
    assert stale is False
    assert "up to date" in msg


def test_dashboard_includes_summary_and_matrix(tmp_path: Path) -> None:
    repo = _populate_repo(tmp_path)
    text = render_dashboard(build_index(repo))
    assert "# alloy-devices-yml coverage dashboard" in text
    assert "Total devices**: 6" in text
    assert "Vendors**: 4" in text
    assert "## Coverage by vendor and source" in text
    # Header lists each source-id.
    assert "stm32" in text
    assert "zephyr-dts" in text
    assert "microchip-dfp" in text
    # Schema-version distribution table appears.
    assert "## Schema version distribution" in text
    assert "1.2.0" in text
    assert "1.2.1" in text


def test_dashboard_handles_empty_catalog(tmp_path: Path) -> None:
    (tmp_path / "vendors").mkdir()
    text = render_dashboard(build_index(tmp_path))
    assert "Total devices**: 0" in text
    assert "Catalog is empty" in text


def test_yaml_with_missing_identity_is_skipped(tmp_path: Path) -> None:
    """Robustness: a malformed YAML doesn't poison the index."""
    repo = _populate_repo(tmp_path)
    bad_path = repo / "vendors" / "st" / "stm32g0" / "devices" / "broken.yml"
    bad_path.write_text("schema_version: 1.2.0\n", encoding="utf-8")  # no identity
    index = build_index(repo)
    assert index.total_devices == 6  # broken.yml dropped, others survive
