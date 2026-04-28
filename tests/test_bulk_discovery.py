"""Tests for `add-bulk-discovery-cmsis-pack-manager` (Phase 2.1):
discovery + sharded fan-out + per-chip failure isolation +
bulk-report.json.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.bulk import (  # noqa: E402
    BulkChipRow,
    enumerate_local_packs,
    run_bulk,
    shard_chips,
    write_bulk_report,
)


def _seed_local_pack_root(tmp_path: Path) -> Path:
    """Stand up a tiny on-disk pack tree with synthetic SVDs."""
    root = tmp_path / "pack-root"
    (root / "g0").mkdir(parents=True)
    for device in ("STM32G030", "STM32G071", "STM32G0B1"):
        (root / "g0" / f"{device}.svd").write_text(
            textwrap.dedent("""\
                <?xml version="1.0"?>
                <device>
                  <name>SYNTH</name>
                  <description>Synthetic</description>
                  <cpu><name>CM0PLUS</name><revision>r0p0</revision></cpu>
                  <peripherals>
                    <peripheral>
                      <name>UART0</name>
                      <baseAddress>0x40010000</baseAddress>
                      <description>UART0</description>
                      <interrupt><name>UART0</name><value>10</value></interrupt>
                    </peripheral>
                  </peripherals>
                </device>
            """),
            encoding="utf-8",
        )
    return root


def test_local_pack_discovery_yields_one_chip_per_svd(tmp_path: Path) -> None:
    root = _seed_local_pack_root(tmp_path)
    rows = list(
        enumerate_local_packs(
            vendor="st",
            family="stm32g0",
            pack_root=root,
            source_id="cmsis-svd",
        )
    )
    devices = sorted(r.device for r in rows)
    assert devices == ["stm32g030", "stm32g071", "stm32g0b1"]
    for row in rows:
        assert "cmsis-svd" in row.source_paths
        assert row.source_paths["cmsis-svd"].exists()


def test_sharding_is_disjoint_and_exhaustive(tmp_path: Path) -> None:
    chips = [
        BulkChipRow(vendor="v", family="f", device=f"d{i}", source_paths={})
        for i in range(50)
    ]
    total = 4
    union: set[str] = set()
    for shard in range(1, total + 1):
        seen = {c.device for c in shard_chips(chips, shard=shard, total_shards=total)}
        # Disjoint with previous shards
        assert seen.isdisjoint(union), f"shard {shard} overlaps prior shards"
        union |= seen
    assert union == {f"d{i}" for i in range(50)}


def test_sharding_is_deterministic(tmp_path: Path) -> None:
    chips = [
        BulkChipRow(vendor="v", family="f", device=f"d{i}", source_paths={})
        for i in range(20)
    ]
    a = [c.device for c in shard_chips(chips, shard=2, total_shards=4)]
    b = [c.device for c in shard_chips(chips, shard=2, total_shards=4)]
    assert a == b


def test_sharding_validates_inputs() -> None:
    with pytest.raises(ValueError, match="total_shards"):
        list(shard_chips([], shard=1, total_shards=0))
    with pytest.raises(ValueError, match="shard must be in"):
        list(shard_chips([], shard=5, total_shards=4))
    with pytest.raises(ValueError, match="shard must be in"):
        list(shard_chips([], shard=0, total_shards=4))


def test_run_bulk_extracts_st_chips_via_stm32_extractor(tmp_path: Path) -> None:
    root = _seed_local_pack_root(tmp_path)
    chips = list(
        enumerate_local_packs(
            vendor="st",
            family="stm32g0",
            pack_root=root,
            source_id="cmsis-svd",
        )
    )
    output_root = tmp_path / "out"
    output_root.mkdir()
    summary = run_bulk(
        chips=chips,
        output_root=output_root,
        revision="bulk-test",
    )
    assert summary.total == 3
    assert summary.passed == 3
    assert summary.failed == 0
    assert summary.skipped == 0
    # Each chip wrote a YAML.
    for r in summary.results:
        assert r.status == "PASS"
        assert r.yaml_path is not None
        assert r.yaml_path.exists()


def test_run_bulk_isolates_failures(tmp_path: Path) -> None:
    """One chip's failure (missing source key, say) does not
    abort the run."""
    output_root = tmp_path / "out"
    output_root.mkdir()
    chips = [
        BulkChipRow(vendor="st", family="stm32g0", device="bad", source_paths={}),
    ]
    summary = run_bulk(chips=chips, output_root=output_root, revision="bulk-test")
    assert summary.total == 1
    assert summary.failed == 1
    assert summary.passed == 0
    assert summary.results[0].status == "EXTRACT_FAILED"
    assert "stm32" in (summary.results[0].error or "")


def test_run_bulk_skips_no_extractor_pair(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    output_root.mkdir()
    chips = [
        BulkChipRow(vendor="acme", family="frob", device="x", source_paths={}),
    ]
    summary = run_bulk(chips=chips, output_root=output_root, revision="bulk-test")
    assert summary.total == 1
    assert summary.failed == 0
    assert summary.skipped == 1
    assert summary.results[0].status == "NO_EXTRACTOR_REGISTERED"


def test_dry_run_does_not_write_yamls(tmp_path: Path) -> None:
    root = _seed_local_pack_root(tmp_path)
    chips = list(
        enumerate_local_packs(
            vendor="st",
            family="stm32g0",
            pack_root=root,
            source_id="cmsis-svd",
        )
    )
    output_root = tmp_path / "out"
    output_root.mkdir()
    summary = run_bulk(
        chips=chips,
        output_root=output_root,
        revision="bulk-test",
        dry_run=True,
    )
    assert summary.passed == 3
    assert all(r.status == "PASS" and r.yaml_path is None for r in summary.results)
    # No YAMLs written.
    assert not list(output_root.rglob("*.yml"))


def test_bulk_report_serialises_status_counts(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    output_root.mkdir()
    chips = [
        BulkChipRow(vendor="acme", family="frob", device="x", source_paths={}),
        BulkChipRow(vendor="st", family="stm32g0", device="bad", source_paths={}),
    ]
    summary = run_bulk(chips=chips, output_root=output_root, revision="bulk-test")
    report_path = tmp_path / "bulk-report.json"
    write_bulk_report(summary, path=report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["total"] == 2
    assert payload["status_counts"]["NO_EXTRACTOR_REGISTERED"] == 1
    assert payload["status_counts"]["EXTRACT_FAILED"] == 1
