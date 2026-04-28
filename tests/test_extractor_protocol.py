"""Tests for the `define-extractor-protocol` (Phase 0.2) work:
the Extractor Protocol, the registry, and the generic resolver.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    ExtractionResult,
    Extractor,
    ExtractorRegistrationError,
    MissingSourceError,
    ProvenanceRecord,
    register_extractor,
    registered_extractor_ids,
    resolve_extractor,
    resolve_extractor_by_id,
)


def test_known_extractors_registered() -> None:
    ids = registered_extractor_ids()
    assert "cmsis-svd" in ids
    assert "zephyr-dts" in ids


def test_resolve_by_id_returns_protocol_instance() -> None:
    ext = resolve_extractor_by_id("cmsis-svd")
    assert isinstance(ext, Extractor)
    assert ext.extractor_id == "cmsis-svd"


def test_resolve_by_id_unknown_raises_with_known_listed() -> None:
    with pytest.raises(ValueError, match="unknown extractor_id") as excinfo:
        resolve_extractor_by_id("not-a-real-extractor")
    assert "cmsis-svd" in str(excinfo.value)


def test_resolve_for_admitted_pair_succeeds() -> None:
    """STM32 has a dedicated extractor that wins via specificity
    over the vendor-wide CMSIS-SVD one."""
    ext = resolve_extractor("st", "stm32g0")
    assert ext.extractor_id == "stm32"


def test_resolve_for_non_specific_vendor_uses_cmsis_svd_catchall() -> None:
    """CMSIS-SVD remains the catch-all for vendors with no
    dedicated family-bound extractor."""
    ext = resolve_extractor("gigadevice", "gd32f4")
    assert ext.extractor_id == "cmsis-svd"


def test_family_specific_wins_over_vendor_wide() -> None:
    """Nordic + nrf52 is admitted by both cmsis-svd (vendor-bound)
    and zephyr-dts (family-bound); the resolver picks the
    family-bound one via specificity."""
    ext = resolve_extractor("nordic", "nrf52")
    assert ext.extractor_id == "zephyr-dts"


def test_ambiguous_family_specific_raises_with_candidate_ids_listed() -> None:
    """Two extractors registering the same (vendor, family) tuple
    must trigger an ambiguity error — caller picks via id."""

    @register_extractor("ambig-a", families=(("ambigvendor", "ambigfam"),))
    class _AmbigA:
        extractor_id: str = "ambig-a"

        def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
            del vendor, family
            return False

        def extract(self, request: ExtractionRequest) -> ExtractionResult:
            del request
            return ExtractionResult(
                payload={},
                provenance=ProvenanceRecord(source_id="x", source_path=None, revision="r"),
            )

    @register_extractor("ambig-b", families=(("ambigvendor", "ambigfam"),))
    class _AmbigB:
        extractor_id: str = "ambig-b"

        def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
            del vendor, family
            return False

        def extract(self, request: ExtractionRequest) -> ExtractionResult:
            del request
            return ExtractionResult(
                payload={},
                provenance=ProvenanceRecord(source_id="x", source_path=None, revision="r"),
            )

    with pytest.raises(ValueError, match="ambiguous") as excinfo:
        resolve_extractor("ambigvendor", "ambigfam")
    msg = str(excinfo.value)
    assert "ambig-a" in msg
    assert "ambig-b" in msg


def test_resolve_for_unknown_pair_raises_with_bindings_listed() -> None:
    with pytest.raises(ValueError, match="no extractor registered") as excinfo:
        resolve_extractor("acme", "frobnicator")
    assert "cmsis-svd" in str(excinfo.value)


def test_extraction_request_dataclass_is_frozen() -> None:
    req = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"cmsis-svd": Path("/tmp/x.svd")},
        revision="abc",
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        req.vendor = "x"  # type: ignore[misc]


def test_extraction_request_require_source_raises_on_missing() -> None:
    req = ExtractionRequest(
        vendor="st",
        family="stm32g0",
        device="stm32g071rb",
        source_paths={"cmsis-svd": Path("/tmp/x.svd")},
        revision="abc",
    )
    with pytest.raises(MissingSourceError, match="not-registered-key") as excinfo:
        req.require_source("not-registered-key")
    assert "cmsis-svd" in str(excinfo.value)


def test_extraction_result_dataclass_is_frozen() -> None:
    res = ExtractionResult(
        payload={},
        provenance=ProvenanceRecord(
            source_id="x",
            source_path=None,
            revision="r",
        ),
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        res.warnings = ()  # type: ignore[misc]


def test_provenance_record_default_extracted_at_is_iso_utc() -> None:
    p = ProvenanceRecord(source_id="x", source_path=None, revision="r")
    assert p.extracted_at.endswith("Z")


def test_register_extractor_rejects_duplicate_id() -> None:
    """Re-registering an existing id must raise — no silent override."""

    @register_extractor("cmsis-svd-clone", vendors=("synth",))
    class _Synth:
        extractor_id: str = "cmsis-svd-clone"

        def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
            del vendor, family
            return False

        def extract(self, request: ExtractionRequest) -> ExtractionResult:
            del request
            return ExtractionResult(
                payload={},
                provenance=ProvenanceRecord(source_id="x", source_path=None, revision="r"),
            )

    with pytest.raises(ExtractorRegistrationError, match="already registered"):
        @register_extractor("cmsis-svd-clone", vendors=("synth",))
        class _Synth2:
            extractor_id: str = "cmsis-svd-clone"

            def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
                del vendor, family
                return False

            def extract(self, request: ExtractionRequest) -> ExtractionResult:
                del request
                return ExtractionResult(
                    payload={},
                    provenance=ProvenanceRecord(source_id="x", source_path=None, revision="r"),
                )


def test_register_extractor_rejects_no_bindings() -> None:
    with pytest.raises(ExtractorRegistrationError, match="must declare"):
        @register_extractor("no-bindings")  # no vendors, no families
        class _NoBind:
            extractor_id: str = "no-bindings"

            def supports(self, vendor: str, family: str) -> bool:
                del vendor, family
                return False

            def extract(self, request: ExtractionRequest) -> ExtractionResult:
                del request
                return ExtractionResult(
                    payload={},
                    provenance=ProvenanceRecord(source_id="x", source_path=None, revision="r"),
                )
