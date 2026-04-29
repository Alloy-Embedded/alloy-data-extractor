"""STM32CubeMX MCU database extractor —
`add-stm32-cubemx-db-extractor` (Phase 3.2).

Reads ST's STM32CubeMX MCU database to enrich STM32 chips with the
authoritative pinmux / DMA / clock-tree facts that CMSIS-SVD lacks.

CubeMX layout this extractor consumes::

    <db>/mcu/<RefName>.xml                — MCU root (pins, IP refs)
    <db>/mcu/IP/GPIO-<Version>_Modes.xml  — AF tables per pin
    <db>/mcu/IP/DMA-<Version>_Modes.xml   — DMA request matrix
    <db>/plugins/clock/<ClockTree>.xml    — clock-tree elements + edges

This extractor is **secondary**: it produces an enrichment payload
shaped like the canonical IR (clock_nodes / clock_selectors /
dma_requests / pins) that
:func:`alloy_data_extractor.merge.merge_payloads` folds onto a
primary STM32 extraction per :data:`STM32_MERGE_POLICY`.

License posture: the extractor refuses to bundle the CubeMX DB.
The user supplies the path via ``--source stm32cubemx-db=<path>``
pointing at the CubeMX install root, the ``db`` directory, or the
``db/mcu`` directory.  ``data/source_pins.toml`` records the
supported CubeMX version (e.g. ``v6.17``) without distributing the
binary.
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
    MissingSourceError,
    ProvenanceRecord,
    register_extractor,
)


# ---------------------------------------------------------------------------
# Typed parse results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CubeMxPin:
    """One MCU-XML <Pin> entry."""

    name: str
    position: str
    pin_type: str
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CubeMxAfRow:
    """One row of the GPIO IP AF table."""

    pin: str
    signal: str
    peripheral: str
    af_number: int


@dataclass(frozen=True, slots=True)
class CubeMxDmaRequest:
    """One enumerated DMA request."""

    peripheral: str
    signal: str
    request_id: int
    request_name: str


@dataclass(frozen=True, slots=True)
class CubeMxClockEdge:
    """A directed edge in the CubeMX clock tree."""

    source: str
    target: str
    signal_id: str


@dataclass(frozen=True, slots=True)
class CubeMxClockNode:
    """A node in the CubeMX clock tree."""

    id: str
    kind: str


@dataclass(frozen=True, slots=True)
class McuFacts:
    """Facts harvested from the MCU root XML."""

    ref_name: str
    family: str
    line: str
    clock_tree: str
    gpio_version: str
    dma_versions: tuple[str, ...]
    pins: tuple[CubeMxPin, ...]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MCU_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    """Strip the XML namespace from a tag name."""
    return _MCU_NS_RE.sub("", tag)


def _iter_named(root: ET.Element, name: str) -> list[ET.Element]:
    """Iterate descendants matching local-name ``name``, namespace-agnostic."""
    return [el for el in root.iter() if _strip_ns(el.tag) == name]


def _findall_named(parent: ET.Element, name: str) -> list[ET.Element]:
    """Return direct children matching local-name ``name``."""
    return [el for el in list(parent) if _strip_ns(el.tag) == name]


def _expand_variants(ref_name: str) -> tuple[str, ...]:
    """Expand CubeMX RefName parens into per-flash variants.

    ``STM32G071R(6-8-B)Tx`` →
      ``("STM32G071R6Tx", "STM32G071R8Tx", "STM32G071RBTx")``.

    Recurses to handle multi-parens names.  Returns ``(ref_name,)``
    if no parens are present.
    """
    match = re.match(r"^([^()]*)\(([^()]+)\)(.*)$", ref_name)
    if not match:
        return (ref_name,)
    prefix, group, suffix = match.groups()
    out: list[str] = []
    for code in group.split("-"):
        out.extend(_expand_variants(prefix + code + suffix))
    return tuple(out)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _find_db_root(supplied: Path) -> tuple[Path, Path] | None:
    """Locate ``db/mcu`` and ``db/plugins/clock`` from a user-supplied path.

    Accepts the CubeMX install root, the ``db`` directory, or the
    ``db/mcu`` directory directly.  Returns ``(mcu_root, clock_root)``
    when both directories are present, else ``None``.
    """
    if not supplied.exists():
        return None

    # Case 1: pointed at the mcu directory.
    if supplied.name == "mcu" and supplied.is_dir():
        mcu = supplied
        clock = supplied.parent / "plugins" / "clock"
        return mcu, clock

    # Case 2: pointed at db/.
    candidate_mcu = supplied / "mcu"
    if candidate_mcu.is_dir():
        return candidate_mcu, supplied / "plugins" / "clock"

    # Case 3: pointed at the install root (Mac .app/Contents/Resources, etc).
    candidate_mcu = supplied / "db" / "mcu"
    if candidate_mcu.is_dir():
        return candidate_mcu, supplied / "db" / "plugins" / "clock"

    # Case 4: macOS .app — inside Contents/Resources.
    candidate_mcu = supplied / "Contents" / "Resources" / "db" / "mcu"
    if candidate_mcu.is_dir():
        return (
            candidate_mcu,
            supplied / "Contents" / "Resources" / "db" / "plugins" / "clock",
        )
    return None


def _match_mcu_xml(mcu_root: Path, device: str) -> Path | None:
    """Return the ``<RefName>.xml`` whose expansion covers ``device``.

    The CubeMX RefName encodes flash variants as ``(6-8-B)`` groups; we
    expand those and match by prefix so device ids like ``stm32g071rb``
    pick up the ``STM32G071RBTx`` variant of ``STM32G071R(6-8-B)Tx.xml``.
    """
    target = device.upper()
    candidates: list[Path] = []
    for path in sorted(mcu_root.glob("STM32*.xml")):
        ref_name = path.stem  # filename without .xml
        for variant in _expand_variants(ref_name):
            if variant.upper().startswith(target):
                candidates.append(path)
                break
    if not candidates:
        return None
    # Deterministic pick: shortest filename wins (prefers the variant
    # file over per-package singleton when both exist), then alpha.
    candidates.sort(key=lambda p: (len(p.name), p.name))
    return candidates[0]


# ---------------------------------------------------------------------------
# MCU XML parsing
# ---------------------------------------------------------------------------


def _parse_mcu_xml(path: Path) -> McuFacts:
    tree = ET.parse(path)
    root = tree.getroot()

    ref_name = root.attrib.get("RefName", path.stem)
    family = root.attrib.get("Family", "")
    line = root.attrib.get("Line", "")
    clock_tree = root.attrib.get("ClockTree", "")

    gpio_version = ""
    dma_versions: list[str] = []
    for ip in _findall_named(root, "IP"):
        ip_name = ip.attrib.get("Name", "")
        version = ip.attrib.get("Version", "")
        if ip_name == "GPIO" and not gpio_version:
            gpio_version = version
        elif ip_name == "DMA" and version not in dma_versions:
            dma_versions.append(version)
        elif ip_name == "BDMA" and version not in dma_versions:
            dma_versions.append(version)

    pins: list[CubeMxPin] = []
    for pin in _findall_named(root, "Pin"):
        name = pin.attrib.get("Name", "")
        signals = tuple(
            s.attrib.get("Name", "")
            for s in _findall_named(pin, "Signal")
            if s.attrib.get("Name")
        )
        pins.append(
            CubeMxPin(
                name=name,
                position=pin.attrib.get("Position", ""),
                pin_type=pin.attrib.get("Type", ""),
                signals=signals,
            )
        )

    return McuFacts(
        ref_name=ref_name,
        family=family,
        line=line,
        clock_tree=clock_tree,
        gpio_version=gpio_version,
        dma_versions=tuple(dma_versions),
        pins=tuple(pins),
    )


# ---------------------------------------------------------------------------
# Pin canonicalization
# ---------------------------------------------------------------------------


_PIN_NAME_RE = re.compile(r"^P([A-Z])(\d+)")


def _canonical_pin_name(raw: str) -> str | None:
    """Reduce a CubeMX pin name like ``"PA9 (PA9)"`` or
    ``"PC14-OSC32_IN (PC14)"`` to the canonical ``"PA9"`` / ``"PC14"``.
    Returns ``None`` if the name doesn't carry a port + index.
    """
    if not raw:
        return None
    text = raw.strip()
    match = _PIN_NAME_RE.match(text)
    if not match:
        return None
    return f"P{match.group(1)}{match.group(2)}"


# ---------------------------------------------------------------------------
# GPIO IP XML — AF table
# ---------------------------------------------------------------------------


_GPIO_AF_RE = re.compile(r"GPIO_AF(\d+)_([A-Z0-9_]+)")


def _parse_gpio_ip_xml(path: Path) -> tuple[CubeMxAfRow, ...]:
    """Parse one ``GPIO-<Version>_Modes.xml`` into AF rows.

    Each ``<GPIO_Pin Name="PA0">`` carries one or more
    ``<PinSignal Name="USART2_TX">`` whose
    ``<SpecificParameter Name="GPIO_AF">/<PossibleValue>`` text encodes
    ``GPIO_AF<n>_<peripheral>``.
    """
    if not path.exists():
        return ()
    tree = ET.parse(path)
    root = tree.getroot()

    rows: list[CubeMxAfRow] = []
    for gpio_pin in _iter_named(root, "GPIO_Pin"):
        pin_name = gpio_pin.attrib.get("Name", "")
        if not pin_name:
            continue
        for pin_signal in _findall_named(gpio_pin, "PinSignal"):
            signal_full = pin_signal.attrib.get("Name", "")
            if not signal_full:
                continue
            af_value: str | None = None
            for spec in _findall_named(pin_signal, "SpecificParameter"):
                if spec.attrib.get("Name") != "GPIO_AF":
                    continue
                possible = next(
                    (v for v in _findall_named(spec, "PossibleValue")), None
                )
                if possible is not None and possible.text:
                    af_value = possible.text.strip()
                    break
            if not af_value:
                continue
            af_match = _GPIO_AF_RE.search(af_value)
            if not af_match:
                continue
            af_number = int(af_match.group(1))
            # Peripheral derives from the signal name's prefix (e.g.
            # USART2_TX → USART2).  The AF macro's suffix is the IP
            # name (USART2) which is sometimes a generic group like
            # COMP1 — using the signal prefix is more granular and
            # matches modm's projection.
            peripheral, _, signal_part = signal_full.partition("_")
            rows.append(
                CubeMxAfRow(
                    pin=pin_name,
                    signal=signal_part or signal_full,
                    peripheral=peripheral,
                    af_number=af_number,
                )
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# DMA IP XML — request matrix
# ---------------------------------------------------------------------------


_DMA_REQUEST_RE = re.compile(r"^DMA_REQUEST_(.+)$")
# Signals that aren't peripheral-bound (memory-to-memory, generators).
_DMA_NONPERIPH = frozenset({"MEM2MEM", "GENERATOR0", "GENERATOR1", "GENERATOR2", "GENERATOR3"})


def _parse_dma_ip_xml(path: Path) -> tuple[CubeMxDmaRequest, ...]:
    """Parse the ``RefParameter Name="Request"`` enumeration of a DMA
    IP file.  Each ``PossibleValue`` is named ``DMA_REQUEST_<NAME>``;
    the index in the enumeration matches the numeric request id used
    by ST's HAL macros (verified against ``stm32g0xx_hal_dma.h``).
    """
    if not path.exists():
        return ()
    tree = ET.parse(path)
    root = tree.getroot()

    out: list[CubeMxDmaRequest] = []
    for ref_param in _iter_named(root, "RefParameter"):
        if ref_param.attrib.get("Name") != "Request":
            continue
        for index, possible in enumerate(_findall_named(ref_param, "PossibleValue")):
            value = possible.attrib.get("Value", "")
            request_match = _DMA_REQUEST_RE.match(value)
            if not request_match:
                continue
            tail = request_match.group(1)  # e.g. "USART1_RX"
            if tail in _DMA_NONPERIPH:
                continue
            peripheral, _, signal = tail.partition("_")
            out.append(
                CubeMxDmaRequest(
                    peripheral=peripheral,
                    signal=signal,
                    request_id=index,
                    request_name=value,
                )
            )
        # First Request-RefParameter wins; the file rarely repeats it.
        break
    return tuple(out)


# ---------------------------------------------------------------------------
# Clock tree
# ---------------------------------------------------------------------------


# Map CubeMX element types onto canonical clock-node kinds.  Anything
# unrecognized falls through to "internal-oscillator" (matches modm's
# default in :func:`alloy_data_extractor.extractors.modm_devices.
# _classify_clock_node`).
_CLOCK_NODE_KIND_FROM_TYPE = {
    "fixedSource": "oscillator",
    "variedSource": "oscillator",
    "devisor": "divider",
    "multiplexor": "selector",
    "multiplicator": "multiplier",
    "output": "output",
    "fixedRatio": "fixed-ratio",
    "activeOutput": "output",
}


def _parse_clocktree_xml(
    path: Path,
) -> tuple[tuple[CubeMxClockNode, ...], tuple[CubeMxClockEdge, ...]]:
    """Return ``(nodes, edges)`` from the clock-tree plugin XML.

    Each ``<Element id="X" type="...">`` becomes a clock node; each
    ``<Output to="Y" signalId="..."/>`` becomes a directed edge.
    """
    if not path.exists():
        return (), ()

    tree = ET.parse(path)
    root = tree.getroot()

    nodes: list[CubeMxClockNode] = []
    edges: list[CubeMxClockEdge] = []
    seen_node_ids: set[str] = set()

    for element in _iter_named(root, "Element"):
        node_id = element.attrib.get("id")
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        kind = _CLOCK_NODE_KIND_FROM_TYPE.get(
            element.attrib.get("type", ""), "internal-oscillator"
        )
        nodes.append(CubeMxClockNode(id=node_id, kind=kind))
        for output in _findall_named(element, "Output"):
            target = output.attrib.get("to")
            if not target:
                continue
            edges.append(
                CubeMxClockEdge(
                    source=node_id,
                    target=target,
                    signal_id=output.attrib.get("signalId", ""),
                )
            )
    return tuple(nodes), tuple(edges)


# ---------------------------------------------------------------------------
# Project to canonical-IR-shaped enrichment payload
# ---------------------------------------------------------------------------


def _cubemx_to_payload(
    *,
    device: str,
    family: str,
    vendor: str,
    mcu: McuFacts,
    af_rows: tuple[CubeMxAfRow, ...],
    dma_requests: tuple[CubeMxDmaRequest, ...],
    clock_nodes: tuple[CubeMxClockNode, ...],
    clock_edges: tuple[CubeMxClockEdge, ...],
    provenance_sha: str,
) -> dict[str, Any]:
    """Project parsed CubeMX tuples into the canonical-IR-shaped dict
    the merge engine consumes.  Mirror's :mod:`modm_devices`'s
    projection so the merge engine can fold either source onto a
    primary STM32 payload uniformly.
    """
    # Pins: aggregate AF rows per canonical pin name.  We look up
    # pin name canonicalization through the MCU XML's <Pin> list so
    # that orphan pins (no AF rows) still surface — they're useful
    # for package-pad coverage.
    pin_to_afs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in af_rows:
        pin_to_afs[row.pin].append(
            {
                "af": row.af_number,
                "peripheral": row.peripheral,
                "signal": row.signal,
            }
        )
    # Add MCU-XML pin entries that didn't appear in the AF table —
    # power pins, NRST, BOOT0, etc. — so the merge engine sees the
    # full package's pinout when CubeMX is the AF authority.
    for pin in mcu.pins:
        canonical = _canonical_pin_name(pin.name)
        if canonical and canonical not in pin_to_afs:
            pin_to_afs[canonical] = []
    pins = [
        {"name": pin_name, "alternate_functions": tuple(afs)}
        for pin_name, afs in sorted(pin_to_afs.items())
    ]

    # DMA requests: one entry per (peripheral, signal) tuple.
    dma_payload = [
        {
            "peripheral": d.peripheral,
            "signal": d.signal,
            "request_id": d.request_id,
            "request_name": d.request_name,
        }
        for d in dma_requests
    ]

    # Clock nodes: include every parsed Element id.  Selectors are
    # the subset of nodes that have multiple incoming edges — same
    # rule the modm projection uses for symmetry.
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in clock_edges:
        if edge.source not in incoming[edge.target]:
            incoming[edge.target].append(edge.source)

    nodes_payload = [{"id": node.id, "kind": node.kind} for node in clock_nodes]
    selectors_payload = [
        {"id": target, "parent_options": tuple(sources)}
        for target, sources in sorted(incoming.items())
        if len(sources) > 1
    ]

    return {
        "schema_version": "1.2.0",
        "identity": {
            "vendor": vendor,
            "family": family,
            "device": device,
            "core": "",
        },
        "provenance": {
            "source_id": "stm32-cubemx",
            "source_path": None,
            "patch_ids": [
                f"stm32-cubemx@{provenance_sha}" if provenance_sha else "stm32-cubemx"
            ],
        },
        "clock_nodes": nodes_payload,
        "clock_selectors": selectors_payload,
        "dma_requests": dma_payload,
        "pins": pins,
    }


# ---------------------------------------------------------------------------
# Extractor protocol adapter
# ---------------------------------------------------------------------------


@register_extractor(
    "stm32-cubemx",
    # Synthetic family — this extractor does NOT win the resolver.
    # It is invoked explicitly by the merge engine / pipeline as a
    # secondary enrichment, mirroring the modm-devices binding.
    families=(("__cubemx_secondary__", "__cubemx_secondary__"),),
)
class Stm32CubeMxExtractor:
    """STM32 CubeMX secondary EnrichmentExtractor."""

    extractor_id: str = "stm32-cubemx"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        if "stm32cubemx-db" not in request.source_paths:
            raise MissingSourceError(
                "stm32-cubemx extractor needs source path keyed "
                "'stm32cubemx-db'.  Install STM32CubeMX (e.g. v6.17) and "
                "pass --source stm32cubemx-db=<path-to-CubeMX-install-or-db-dir>.  "
                f"Got source keys: {sorted(request.source_paths)}"
            )

        supplied = request.source_paths["stm32cubemx-db"]
        roots = _find_db_root(supplied)
        if roots is None:
            raise ValueError(
                "stm32-cubemx extractor: cannot locate the CubeMX MCU "
                f"database under {supplied}.  Expected one of "
                "<root>/db/mcu/, <root>/mcu/, or a direct mcu/ folder.  "
                "Phase 3.2 (`add-stm32-cubemx-db-extractor`)."
            )
        mcu_root, clock_root = roots

        mcu_xml = _match_mcu_xml(mcu_root, request.device)
        if mcu_xml is None:
            raise ValueError(
                f"stm32-cubemx extractor: no MCU XML in {mcu_root} "
                f"matches device {request.device!r}.  Tried "
                "expanding RefName variants like 'STM32G071R(6-8-B)Tx'."
            )

        facts = _parse_mcu_xml(mcu_xml)

        ip_dir = mcu_root / "IP"
        af_rows: tuple[CubeMxAfRow, ...] = ()
        if facts.gpio_version:
            af_rows = _parse_gpio_ip_xml(
                ip_dir / f"GPIO-{facts.gpio_version}_Modes.xml"
            )

        dma_requests: list[CubeMxDmaRequest] = []
        for dma_version in facts.dma_versions:
            dma_requests.extend(
                _parse_dma_ip_xml(ip_dir / f"DMA-{dma_version}_Modes.xml")
            )

        clock_nodes: tuple[CubeMxClockNode, ...] = ()
        clock_edges: tuple[CubeMxClockEdge, ...] = ()
        if facts.clock_tree:
            candidate = clock_root / f"{facts.clock_tree}.xml"
            if candidate.exists():
                clock_nodes, clock_edges = _parse_clocktree_xml(candidate)

        payload = _cubemx_to_payload(
            device=request.device,
            family=request.family,
            vendor=request.vendor,
            mcu=facts,
            af_rows=af_rows,
            dma_requests=tuple(dma_requests),
            clock_nodes=clock_nodes,
            clock_edges=clock_edges,
            provenance_sha=request.revision,
        )

        warnings: list[str] = [
            "stm32-cubemx is a secondary enrichment — "
            "compose with a primary extraction via "
            "alloy_data_extractor.merge.merge_payloads(...).",
        ]
        if not af_rows:
            warnings.append(
                f"stm32-cubemx: no AF rows for {request.device} "
                f"(GPIO IP version {facts.gpio_version!r} not found "
                f"in {ip_dir})."
            )
        if not clock_nodes:
            warnings.append(
                f"stm32-cubemx: no clock-tree edges for "
                f"{request.device} (ClockTree={facts.clock_tree!r})."
            )

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="stm32-cubemx",
                source_path=str(mcu_xml),
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = [
    "CubeMxAfRow",
    "CubeMxClockEdge",
    "CubeMxClockNode",
    "CubeMxDmaRequest",
    "CubeMxPin",
    "McuFacts",
    "Stm32CubeMxExtractor",
]
