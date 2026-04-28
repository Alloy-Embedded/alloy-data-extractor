"""Tests for `add-riscv-community-svd-extractor` (Phase 3.4):
the community RISC-V vendors plug into the existing CMSIS-SVD
extractor via the registry's vendor-wide binding.
"""

from __future__ import annotations

import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    resolve_extractor,
)

_COMMUNITY_RISCV_VENDORS = (
    "gigadevice",
    "bouffalo",
    "wch",
    "kendryte",
    "allwinner",
)


@pytest.mark.parametrize("vendor", _COMMUNITY_RISCV_VENDORS)
def test_community_riscv_vendor_resolves_to_cmsis_svd(vendor: str) -> None:
    """Each community RISC-V vendor admits via the catch-all
    CMSIS-SVD extractor (no vendor-specific extractor needed)."""
    ext = resolve_extractor(vendor, f"{vendor}-fam")
    assert ext.extractor_id == "cmsis-svd"


@pytest.mark.parametrize("vendor", _COMMUNITY_RISCV_VENDORS)
def test_community_riscv_pin_entry_present(vendor: str) -> None:
    """Each community RISC-V vendor has an entry in
    data/source_pins.toml with origin_url + revision + license."""
    pin_path = ROOT / "data" / "source_pins.toml"
    pins = tomllib.loads(pin_path.read_text(encoding="utf-8"))
    key = f"{vendor}-svd"
    assert key in pins, f"missing pin entry: [{key}]"
    entry = pins[key]
    for field in ("origin_url", "revision", "license"):
        assert field in entry, f"[{key}] missing required field: {field}"
        assert entry[field], f"[{key}].{field} is empty"


def test_community_riscv_chip_extracts_via_cmsis_svd(tmp_path: Path) -> None:
    """End-to-end smoke test: a synthetic GD32V SVD goes through
    the CMSIS-SVD extractor without special handling."""
    svd_text = textwrap.dedent("""\
        <?xml version="1.0"?>
        <device>
          <name>GD32VSYNTH</name>
          <description>Synthetic GD32V test device</description>
          <cpu>
            <name>other</name>
            <revision>r0p0</revision>
          </cpu>
          <peripherals>
            <peripheral>
              <name>USART0</name>
              <baseAddress>0x40013800</baseAddress>
              <description>USART0</description>
              <interrupt><name>USART0</name><value>27</value></interrupt>
            </peripheral>
          </peripherals>
        </device>
    """)
    svd_path = tmp_path / "gd32vsynth.svd"
    svd_path.write_text(svd_text, encoding="utf-8")

    ext = resolve_extractor("gigadevice", "gd32vf1")
    request = ExtractionRequest(
        vendor="gigadevice",
        family="gd32vf1",
        device="gd32vf103cbt6",
        source_paths={"cmsis-svd": svd_path},
        revision="riscv-test",
    )
    result = ext.extract(request)
    assert result.payload["identity"]["vendor"] == "gigadevice"
    assert result.payload["provenance"]["source_id"] == "cmsis-svd"
    assert any(p["name"] == "USART0" for p in result.payload["peripherals"])


def test_riscv_vendors_dont_collide_with_dedicated_extractors() -> None:
    """Sanity: community RISC-V vendors don't accidentally
    register their own family-bound extractor (which would cause
    ambiguity)."""
    # Only the cmsis-svd vendor-wide binding admits these.
    ext = resolve_extractor("wch", "ch32v3")
    assert ext.extractor_id == "cmsis-svd"
