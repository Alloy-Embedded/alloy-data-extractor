"""STM32 open-pin-data parser.

Reads the STM32_open_pin_data XML format that ST publishes
(``mcu/<RefName>.xml`` per chip + ``mcu/IP/GPIO-<version>_Modes.xml``
for the GPIO AF tables) and projects it into a canonical-IR-
shaped enrichment payload that the merge engine folds onto a
primary STM32 CMSIS-SVD extraction.

What this DOES:

* Parse the per-chip MCU XML to extract pin → signal mappings,
  pin port/number identity (PA0, PB12, ...), and package-pad
  information.
* Cross-reference each signal name with the GPIO modes XML
  (``GPIO-<version>_Modes.xml``) to resolve the alternate-
  function (AF) number.
* Project the result into ``pins`` (with per-pin AF tables) and
  ``package_pads`` (physical package pad layout) shapes the
  merge engine consumes.

Used as a **secondary** EnrichmentExtractor — the primary
register/peripheral data still comes from CMSIS-SVD.  The
:data:`STM32_MERGE_POLICY` declares ``stm32-open-pin-data`` as
the authoritative source for ``pins`` (taking precedence over
modm-devices when both supply pins).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)

XML_NAMESPACE = {"st": "http://dummy.com"}
PIN_NAME_PATTERN = re.compile(r"\bP(?P<port>[A-Z])(?P<number>\d+)\b")
PACKAGE_PIN_COUNT_PATTERN = re.compile(r"(?P<count>\d+)$")
GPIO_AF_PATTERN = re.compile(r"GPIO_AF(?P<af>\d+)_")


@dataclass(frozen=True, slots=True)
class PinAlternateFunction:
    signal_name: str
    af_number: int


@dataclass(frozen=True, slots=True)
class PinDocumentEntry:
    name: str
    port: str
    number: int
    signals: tuple[PinAlternateFunction, ...] = ()


@dataclass(frozen=True, slots=True)
class PackagePadEntry:
    pad_id: str
    position_label: str
    physical_index: int | None
    pad_kind: str
    bonded_pin: str | None
    bonding_state: str


@dataclass(frozen=True, slots=True)
class PinDataDocument:
    device_name: str
    package_name: str
    package_pin_count: int | None
    pins: tuple[PinDocumentEntry, ...]
    package_pads: tuple[PackagePadEntry, ...]
    gpio_modes_file: str


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _extract_pin_identity(raw_name: str) -> tuple[str, str, int] | None:
    """Strip ``PA9-OSC32_OUT (PB12)`` style noise to ``("PA9", "A", 9)``."""
    match = PIN_NAME_PATTERN.search(raw_name)
    if match is None:
        return None
    port = match.group("port")
    number = int(match.group("number"))
    return f"P{port}{number}", port, number


def _extract_package_pin_count(package_name: str) -> int | None:
    match = PACKAGE_PIN_COUNT_PATTERN.search(package_name)
    if match is None:
        return None
    return int(match.group("count"))


def _pad_kind(raw_type: str | None, raw_name: str) -> str:
    normalized_type = (raw_type or "").strip().lower()
    normalized_name = raw_name.strip().lower()
    if normalized_name == "nc" or normalized_name.startswith("nc"):
        return "nc"
    if normalized_type in {"i/o", "io"}:
        return "io"
    if "power" in normalized_type or normalized_name.startswith("v"):
        return "power"
    if "ground" in normalized_type or normalized_name.startswith("gnd"):
        return "ground"
    if "reset" in normalized_type or normalized_name in {"nrst", "reset"}:
        return "reset"
    if "boot" in normalized_name:
        return "boot"
    return normalized_type.replace("/", "-").replace(" ", "-") or "signal"


def _parse_af_number(pin_signal: ET.Element) -> int | None:
    for parameter in pin_signal.findall("st:SpecificParameter", XML_NAMESPACE):
        if parameter.get("Name") != "GPIO_AF":
            continue
        possible = parameter.find("st:PossibleValue", XML_NAMESPACE)
        if possible is None or possible.text is None:
            continue
        match = GPIO_AF_PATTERN.search(possible.text)
        if match is not None:
            return int(match.group("af"))
    return None


def _parse_gpio_modes_file_name(mcu_root: ET.Element) -> str | None:
    """Find the GPIO IP version declared inside the MCU XML; return
    the corresponding modes-file basename (``GPIO-<version>_Modes.xml``)
    or None when absent.
    """
    for ip_node in mcu_root.findall("st:IP", XML_NAMESPACE):
        if ip_node.get("Name") != "GPIO":
            continue
        version = ip_node.get("Version")
        if version:
            return f"GPIO-{version}_Modes.xml"
    return None


def _parse_gpio_modes(modes_path: Path) -> dict[str, dict[str, int]]:
    """Return ``{pin_name: {signal_name: af_number}}`` from a
    ``GPIO-<version>_Modes.xml`` file."""
    modes_root = ET.parse(modes_path).getroot()
    signals_by_pin: dict[str, dict[str, int]] = {}
    for gpio_pin in modes_root.findall(".//st:GPIO_Pin", XML_NAMESPACE):
        pin_name = gpio_pin.get("Name")
        if not pin_name:
            continue
        pin_signals: dict[str, int] = {}
        for pin_signal in gpio_pin.findall("st:PinSignal", XML_NAMESPACE):
            signal_name = pin_signal.get("Name")
            af_number = _parse_af_number(pin_signal)
            if signal_name and af_number is not None:
                pin_signals[signal_name] = af_number
        signals_by_pin[pin_name] = pin_signals
    return signals_by_pin


def _resolve_af_number(signal_name: str, available_signals: dict[str, int]) -> int | None:
    """Match ``USART1_TX`` exactly first; fall back to a unique
    prefix match (e.g. ``USART2_TX_RX_DE`` against ``USART2_TX``)."""
    exact = available_signals.get(signal_name)
    if exact is not None:
        return exact
    prefix_matches = {
        af_number
        for candidate, af_number in available_signals.items()
        if signal_name.startswith(candidate) or candidate.startswith(signal_name)
    }
    if len(prefix_matches) == 1:
        return next(iter(prefix_matches))
    return None


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------


def parse_pin_data_document(*, mcu_path: Path, gpio_modes_path: Path) -> PinDataDocument:
    """Parse the chip's MCU XML + GPIO modes XML into a typed document.

    The parser is intentionally tolerant: pins without a clean
    ``P[A-Z]\\d+`` identity (power / ground / NC / reset / boot)
    show up as ``PackagePadEntry`` rows but not in ``pins``.
    """
    mcu_root = ET.parse(mcu_path).getroot()
    available_signals = _parse_gpio_modes(gpio_modes_path)
    package_name = (mcu_root.get("Package") or "").lower()

    pins_by_position: dict[int, PinDocumentEntry] = {}
    pins_without_position: list[PinDocumentEntry] = []
    package_pads_by_position: dict[int, PackagePadEntry] = {}
    package_pads_without_position: list[PackagePadEntry] = []

    for pin_node in mcu_root.findall("st:Pin", XML_NAMESPACE):
        raw_name = pin_node.get("Name") or ""
        position_text = pin_node.get("Position")
        identity = _extract_pin_identity(raw_name)
        raw_pad = PackagePadEntry(
            pad_id=position_text or raw_name,
            position_label=position_text or raw_name,
            physical_index=(
                int(position_text)
                if position_text is not None and position_text.isdigit()
                else None
            ),
            pad_kind=_pad_kind(pin_node.get("Type"), raw_name),
            bonded_pin=None if identity is None else identity[0],
            bonding_state=(
                "bonded"
                if identity is not None
                else (
                    "unbonded"
                    if _pad_kind(pin_node.get("Type"), raw_name) == "nc"
                    else "dedicated"
                )
            ),
        )
        if position_text is not None and position_text.isdigit():
            package_pads_by_position.setdefault(int(position_text), raw_pad)
        else:
            package_pads_without_position.append(raw_pad)

        if identity is None:
            continue
        pin_name, port, number = identity

        af_signals: list[PinAlternateFunction] = []
        available_by_signal = available_signals.get(pin_name, {})
        for signal_node in pin_node.findall("st:Signal", XML_NAMESPACE):
            signal_name = signal_node.get("Name")
            if signal_name is None or signal_name == "GPIO":
                continue
            af_number = _resolve_af_number(signal_name, available_by_signal)
            if af_number is None:
                continue
            af_signals.append(
                PinAlternateFunction(signal_name=signal_name, af_number=af_number)
            )

        entry = PinDocumentEntry(
            name=pin_name,
            port=port,
            number=number,
            signals=tuple(
                sorted(af_signals, key=lambda s: (s.af_number, s.signal_name))
            ),
        )
        if position_text is not None and position_text.isdigit():
            pins_by_position.setdefault(int(position_text), entry)
        else:
            pins_without_position.append(entry)

    return PinDataDocument(
        device_name=(mcu_root.get("RefName") or mcu_path.stem).lower(),
        package_name=package_name,
        package_pin_count=_extract_package_pin_count(package_name),
        pins=tuple(
            [pins_by_position[p] for p in sorted(pins_by_position)]
            + sorted(
                pins_without_position,
                key=lambda e: (e.port, e.number, e.name),
            )
        ),
        package_pads=tuple(
            sorted(
                [
                    package_pads_by_position[p]
                    for p in sorted(package_pads_by_position)
                ]
                + package_pads_without_position,
                key=lambda p: (
                    p.physical_index is None,
                    -1 if p.physical_index is None else p.physical_index,
                    p.position_label,
                    p.pad_id,
                ),
            )
        ),
        gpio_modes_file=gpio_modes_path.name,
    )


# ---------------------------------------------------------------------------
# Project to canonical-payload shape
# ---------------------------------------------------------------------------


def _project_to_payload(
    *,
    vendor: str,
    family: str,
    device: str,
    pin_doc: PinDataDocument,
    source_path: Path,
    revision: str,
) -> dict[str, Any]:
    pins: list[dict[str, Any]] = []
    for entry in pin_doc.pins:
        afs = [
            {
                "af": s.af_number,
                "signal": s.signal_name,
                "peripheral": s.signal_name.split("_", 1)[0] if "_" in s.signal_name else "",
            }
            for s in entry.signals
        ]
        pins.append(
            {
                "name": entry.name,
                "port": entry.port,
                "number": entry.number,
                "alternate_functions": afs,
            }
        )

    pads: list[dict[str, Any]] = [
        {
            "pad_id": p.pad_id,
            "position_label": p.position_label,
            "physical_index": p.physical_index,
            "pad_kind": p.pad_kind,
            "bonded_pin": p.bonded_pin,
            "bonding_state": p.bonding_state,
        }
        for p in pin_doc.package_pads
    ]

    return {
        "schema_version": "1.2.0",
        "identity": {
            "vendor": vendor,
            "family": family,
            "device": device,
            "package": pin_doc.package_name,
            "core": "",
        },
        "provenance": {
            "source_id": "stm32-open-pin-data",
            "source_path": str(source_path),
            "patch_ids": [f"stm32-open-pin-data@{revision}"],
        },
        "pins": pins,
        "package_pads": pads,
    }


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_paths(
    request: ExtractionRequest,
) -> tuple[Path, Path] | None:
    """Locate the (MCU XML, GPIO modes XML) pair from request.

    ``source_paths`` shapes:
      * ``stm32-open-pin-data`` — root of the STM32_open_pin_data
        repo; we walk ``mcu/<RefName>*.xml`` and the matching
        ``mcu/IP/GPIO-<version>_Modes.xml``.
      * ``stm32-open-pin-data-mcu`` — direct path to the MCU XML.
      * ``stm32-open-pin-data-gpio`` — direct path to the GPIO
        modes XML.
    """
    mcu_path = request.source_paths.get("stm32-open-pin-data-mcu")
    gpio_path = request.source_paths.get("stm32-open-pin-data-gpio")
    if mcu_path is None and "stm32-open-pin-data" in request.source_paths:
        root = request.source_paths["stm32-open-pin-data"]
        # Walk mcu/ for any XML matching the device prefix.
        upper = request.device.upper()
        for cand in (root / "mcu").glob(f"{upper}*.xml"):
            mcu_path = cand
            break
    if mcu_path is None or not mcu_path.exists():
        return None
    if gpio_path is None and "stm32-open-pin-data" in request.source_paths:
        # Resolve from the modes-file name embedded in the MCU XML.
        try:
            mcu_root = ET.parse(mcu_path).getroot()
        except ET.ParseError:
            return None
        modes_filename = _parse_gpio_modes_file_name(mcu_root)
        if modes_filename:
            gpio_path = request.source_paths["stm32-open-pin-data"] / "mcu" / "IP" / modes_filename
    if gpio_path is None or not gpio_path.exists():
        return None
    return mcu_path, gpio_path


# ---------------------------------------------------------------------------
# Extractor protocol adapter
# ---------------------------------------------------------------------------


@register_extractor(
    "stm32-open-pin-data",
    # Synthetic family — this is a secondary EnrichmentExtractor;
    # invoked explicitly via the merge engine, not auto-resolved.
    families=(("__stm32_open_pin_data_secondary__", "__stm32_open_pin_data_secondary__"),),
)
class Stm32OpenPinDataExtractor:
    """STM32 open-pin-data secondary EnrichmentExtractor."""

    extractor_id: str = "stm32-open-pin-data"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        paths = _resolve_paths(request)
        if paths is None:
            available = sorted(request.source_paths)
            raise ValueError(
                "stm32-open-pin-data extractor: cannot resolve MCU + "
                f"GPIO modes XML for {request.device}.  Pass either "
                f"--source stm32-open-pin-data=<repo-root> or both "
                f"--source stm32-open-pin-data-mcu=<path> and "
                f"--source stm32-open-pin-data-gpio=<path>.  "
                f"Got source keys: {available}"
            )
        mcu_path, gpio_path = paths
        document = parse_pin_data_document(mcu_path=mcu_path, gpio_modes_path=gpio_path)
        payload = _project_to_payload(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            pin_doc=document,
            source_path=mcu_path,
            revision=request.revision,
        )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="stm32-open-pin-data",
                source_path=str(mcu_path),
                revision=request.revision,
            ),
            warnings=(
                "stm32-open-pin-data is a secondary enrichment — "
                "compose with a primary STM32 extraction via "
                "alloy_data_extractor.merge.merge_payloads(...).",
            ),
        )


# Ensure defaultdict isn't dead-stripped (used implicitly for grouping).
del defaultdict


__all__ = [
    "PackagePadEntry",
    "PinAlternateFunction",
    "PinDataDocument",
    "PinDocumentEntry",
    "Stm32OpenPinDataExtractor",
    "parse_pin_data_document",
]
