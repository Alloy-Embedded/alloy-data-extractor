"""Tests for the cmsis-pack-manager backed extractor.

These tests are unit-level and exercise the pure-function
helpers (vendor / core mapping, prefix matching, SVD-from-pack
extraction).  End-to-end tests against the real CMSIS-Pack
catalog would require network — out of scope for a unit suite.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401
from alloy_data_extractor.extractor_protocol import resolve_extractor_by_id  # noqa: E402
from alloy_data_extractor.extractors.cmsis_pack import (  # noqa: E402
    _alloy_core_for_record,
    _alloy_vendor_for_record,
    _common_prefix,
    extract_svd_from_pack,
)


def test_alloy_vendor_strips_vendor_id_suffix() -> None:
    assert _alloy_vendor_for_record({"vendor": "STMicroelectronics:13"}) == "st"
    assert _alloy_vendor_for_record({"vendor": "Texas Instruments:5"}) == "ti"
    assert _alloy_vendor_for_record({"vendor": "Nordic Semiconductor:7"}) == "nordic"
    assert _alloy_vendor_for_record({"vendor": "SiliconLabs:54"}) == "siliconlabs"


def test_alloy_vendor_handles_missing_vendor() -> None:
    assert _alloy_vendor_for_record({}) == ""
    assert _alloy_vendor_for_record({"vendor": None}) == ""


def test_alloy_core_synthesizes_fpu_suffix() -> None:
    """When the catalog record names CortexM4 + FPU=SP_FP we
    promote to alloy's `cortex-m4f` value."""
    record = {"processors": [{"core": "CortexM4", "fpu": "SP_FP"}]}
    assert _alloy_core_for_record(record) == "cortex-m4f"


def test_alloy_core_keeps_plain_name_when_no_fpu() -> None:
    record = {"processors": [{"core": "CortexM3", "fpu": "None"}]}
    assert _alloy_core_for_record(record) == "cortex-m3"


def test_alloy_core_maps_known_variants() -> None:
    cases = [
        ("CortexM0", "cortex-m0"),
        ("CortexM0Plus", "cortex-m0plus"),
        ("CortexM23", "cortex-m23"),
        ("CortexM33", "cortex-m33"),
        ("CortexM55", "cortex-m55"),
    ]
    for raw, expected in cases:
        record = {"processors": [{"core": raw, "fpu": "None"}]}
        assert _alloy_core_for_record(record) == expected, raw


def test_alloy_core_returns_empty_when_processors_missing() -> None:
    assert _alloy_core_for_record({}) == ""
    assert _alloy_core_for_record({"processors": []}) == ""


def test_common_prefix() -> None:
    assert _common_prefix("STM32G071C8Tx", "STM32G071") == "STM32G071"
    assert _common_prefix("STM32G071", "STM32G071") == "STM32G071"
    assert _common_prefix("ABC", "DEF") == ""
    assert _common_prefix("", "anything") == ""


def test_extract_svd_from_pack_picks_longest_prefix(tmp_path: Path) -> None:
    """When a pack ships multiple SVDs, the extractor picks the
    one whose stem shares the longest prefix with the chip name."""
    pack_path = tmp_path / "synth.pack"
    with zipfile.ZipFile(pack_path, "w") as zf:
        zf.writestr("CMSIS/SVD/STM32G030.svd", "<device>g030</device>")
        zf.writestr("CMSIS/SVD/STM32G071.svd", "<device>g071</device>")
        zf.writestr("CMSIS/SVD/STM32G0B1.svd", "<device>g0b1</device>")

    work_dir = tmp_path / "extracted"
    chosen = extract_svd_from_pack(pack_path, "STM32G071C8Tx", work_dir=work_dir)
    assert chosen is not None
    assert chosen.name == "STM32G071.svd"
    assert chosen.read_text() == "<device>g071</device>"


def test_extract_svd_from_pack_returns_none_when_no_svd(tmp_path: Path) -> None:
    pack_path = tmp_path / "synth.pack"
    with zipfile.ZipFile(pack_path, "w") as zf:
        zf.writestr("Documents/readme.txt", "just docs")
    chosen = extract_svd_from_pack(
        pack_path, "STM32G071", work_dir=tmp_path / "out"
    )
    assert chosen is None


def test_cmsis_pack_extractor_resolves_via_id() -> None:
    ext = resolve_extractor_by_id("cmsis-pack")
    assert ext.extractor_id == "cmsis-pack"


def test_cmsis_pack_extractor_raises_for_unknown_chip() -> None:
    """When the chip name isn't in the catalog, the extractor
    surfaces a clear ValueError (no silent crash)."""
    from alloy_data_extractor.extractor_protocol import ExtractionRequest

    ext = resolve_extractor_by_id("cmsis-pack")
    request = ExtractionRequest(
        vendor="acme",
        family="frob",
        device="ACME_FROBNICATOR_NOT_REAL",
        source_paths={},
        revision="r",
    )
    with pytest.raises(ValueError, match="not in the CMSIS-Pack catalog"):
        ext.extract(request)
