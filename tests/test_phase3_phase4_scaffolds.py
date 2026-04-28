"""Verifies the Phase 3 + Phase 4 extractor scaffolds register
correctly and surface the expected NotImplementedError when
called.  These are the placeholders that bulk discovery uses
to route chips to the eventual implementations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alloy_data_extractor.pipeline  # noqa: E402,F401  (registers extractors)
from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    registered_extractor_ids,
    resolve_extractor,
    resolve_extractor_by_id,
)

_PHASE3_PRIMARY_BINDINGS = (
    # PIC (Phase 3.1)
    ("microchip", "pic18", "microchip-pic"),
    ("microchip", "pic16f", "microchip-pic"),
    ("microchip", "pic24f", "microchip-pic"),
    ("microchip", "pic32mz", "microchip-pic"),
    ("microchip", "dspic33", "microchip-pic"),
    # MSP430 (Phase 3.3)
    ("ti", "msp430", "msp430"),
)


_PHASE4_BINDINGS = (
    # 8051 (Phase 4.2)
    ("nuvoton", "n76", "intel-8051"),
    ("nuvoton", "n79", "intel-8051"),
    ("silabs", "efm8", "intel-8051"),
    ("stc", "stc15w", "intel-8051"),
)


@pytest.mark.parametrize(
    ("vendor", "family", "expected_id"),
    _PHASE3_PRIMARY_BINDINGS + _PHASE4_BINDINGS,
)
def test_scaffold_resolves(vendor: str, family: str, expected_id: str) -> None:
    ext = resolve_extractor(vendor, family)
    assert ext.extractor_id == expected_id


def test_phase3_phase4_extractors_are_in_registry() -> None:
    ids = registered_extractor_ids()
    expected_ids = {
        "microchip-pic",
        "stm32-cubemx",
        "msp430",
        "datasheet-pdf",
        "intel-8051",
    }
    assert expected_ids.issubset(set(ids))


@pytest.mark.parametrize(
    ("extractor_id", "phase_marker"),
    [
        ("microchip-pic", "Phase 3.1"),
        ("stm32-cubemx", "Phase 3.2"),
        ("msp430", "Phase 3.3"),
        # `datasheet-pdf` is no longer a stub — it has a real
        # pdfminer.six implementation as of Phase 4.1.  Tested
        # separately in tests/test_datasheet_pdf_extractor.py.
        ("intel-8051", "Phase 4.2"),
    ],
)
def test_scaffold_extract_raises_with_phase_marker(
    extractor_id: str, phase_marker: str
) -> None:
    """Each scaffold's NotImplementedError mentions the matching
    OpenSpec phase ID — so callers that hit a stub know exactly
    which OpenSpec to chase up."""
    ext = resolve_extractor_by_id(extractor_id)
    request = ExtractionRequest(
        vendor="x",
        family="y",
        device="z",
        source_paths={},
        revision="r",
    )
    with pytest.raises(NotImplementedError) as excinfo:
        ext.extract(request)
    msg = str(excinfo.value)
    assert phase_marker in msg, (
        f"{extractor_id} stub does not reference {phase_marker}: {msg}"
    )


def test_secondary_extractors_do_not_win_resolver() -> None:
    """`stm32-cubemx` and `datasheet-pdf` are secondary
    enrichments — they MUST NOT win the resolver for any real
    vendor pair (they're invoked via merge engine / explicit
    template lookup, not auto-resolution)."""
    # ST families must still resolve to the primary stm32 extractor.
    assert resolve_extractor("st", "stm32g0").extractor_id == "stm32"
    # Synthetic PDF families resolve only via id, not vendor lookup.
    with pytest.raises(ValueError, match="no extractor registered"):
        resolve_extractor("pdf-only-vendor", "pdf-only-family")
