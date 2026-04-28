"""modm-devices XML enrichment extractor —
`migrate-modm-enrichment-extractor` (Phase 1.7).

modm-io's `modm-devices` repo carries already-normalized AF
tables, clock-tree topology, and DMA request matrices for ~3500
STM32 variants — extracted from CubeMX XML and ST reference
manual PDFs by `modm-data`.

This extractor is **secondary**: it does not produce a primary
canonical YAML; it produces a payload shaped for the merge
engine (Phase 2.2 :func:`alloy_data_extractor.merge.merge_payloads`)
to fold onto a primary STM32 extraction.

Field shape (post-merge):

* ``clock_nodes`` — modm RCC clock-tree edges projected as
  ``ClockNodeLite``-shaped dicts.
* ``clock_selectors`` — multi-input mux nodes derived from the
  clock-tree edges.
* ``dma_bindings`` — modm DMA request matrix.
* ``pins`` — modm AF tables (per-pin alternate-function rows).

The reference :data:`alloy_data_extractor.merge.STM32_MERGE_POLICY`
declares modm-devices as the authoritative source for
``clock_nodes``, ``clock_selectors``, and ``dma_bindings``.
"""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class ModmClockEdge:
    source: str
    target: str
    multiplier: int | None = None
    divisor: int | None = None


@dataclass(frozen=True, slots=True)
class ModmDmaRequest:
    peripheral: str
    signal: str
    request_value: int


@dataclass(frozen=True, slots=True)
class ModmSignalAf:
    pin: str
    peripheral: str
    signal: str
    af_number: int


def _parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_modm_xml(
    path: Path,
) -> tuple[
    tuple[ModmClockEdge, ...],
    tuple[ModmDmaRequest, ...],
    tuple[ModmSignalAf, ...],
]:
    """Parse one modm-devices XML into typed enrichment tuples."""
    tree = ET.parse(path)
    root = tree.getroot()

    clock_edges: list[ModmClockEdge] = []
    dma_requests: list[ModmDmaRequest] = []
    signal_afs: list[ModmSignalAf] = []

    device_elements = list(root.iter("device"))
    if not device_elements:
        device_elements = [root]

    for device in device_elements:
        for driver in device.iter("driver"):
            driver_name = (driver.attrib.get("name") or "").lower()
            if driver_name == "rcc":
                for edge in driver.iter("signal"):
                    src = edge.attrib.get("source", "")
                    tgt = edge.attrib.get("target", "")
                    if not (src and tgt):
                        continue
                    clock_edges.append(
                        ModmClockEdge(
                            source=src,
                            target=tgt,
                            multiplier=_parse_int(edge.attrib.get("multiplier")),
                            divisor=_parse_int(edge.attrib.get("divisor")),
                        )
                    )
            elif driver_name == "dma":
                for request in driver.iter("request"):
                    peripheral = request.attrib.get("peripheral", "")
                    signal = request.attrib.get("signal", "")
                    channel = _parse_int(request.attrib.get("channel")) or 0
                    if peripheral:
                        dma_requests.append(
                            ModmDmaRequest(
                                peripheral=peripheral,
                                signal=signal,
                                request_value=channel,
                            )
                        )
            elif driver_name == "gpio":
                for gpio in driver.iter("gpio"):
                    port = (gpio.attrib.get("port") or "").upper()
                    pin_number = _parse_int(gpio.attrib.get("pin"))
                    if pin_number is None or not port:
                        continue
                    pin_label = f"P{port}{pin_number}"
                    for signal in gpio.iter("signal"):
                        peri_driver = signal.attrib.get("driver", "")
                        instance = signal.attrib.get("instance", "")
                        signal_name = signal.attrib.get("name", "")
                        af = _parse_int(signal.attrib.get("af"))
                        if af is None or not (peri_driver and signal_name):
                            continue
                        peripheral = f"{peri_driver.upper()}{instance}" if peri_driver else ""
                        signal_afs.append(
                            ModmSignalAf(
                                pin=pin_label,
                                peripheral=peripheral,
                                signal=signal_name,
                                af_number=af,
                            )
                        )

    return tuple(clock_edges), tuple(dma_requests), tuple(signal_afs)


# ---------------------------------------------------------------------------
# Project to canonical-IR-shaped enrichment payload
# ---------------------------------------------------------------------------


def _modm_to_payload(
    *,
    device: str,
    family: str,
    vendor: str,
    clock_edges: tuple[ModmClockEdge, ...],
    dma_requests: tuple[ModmDmaRequest, ...],
    signal_afs: tuple[ModmSignalAf, ...],
    provenance_sha: str,
) -> dict[str, Any]:
    """Project parsed modm tuples into the canonical-IR-shaped
    dict the merge engine consumes.
    """
    # Clock nodes: every distinct source / target becomes one node.
    nodes_seen: set[str] = set()
    clock_nodes: list[dict[str, Any]] = []
    for edge in clock_edges:
        for node_id in (edge.source, edge.target):
            if node_id in nodes_seen:
                continue
            nodes_seen.add(node_id)
            clock_nodes.append(
                {
                    "id": node_id,
                    "kind": _classify_clock_node(node_id),
                }
            )

    # Selectors: targets that have multiple distinct sources.
    target_to_sources: dict[str, list[str]] = defaultdict(list)
    for edge in clock_edges:
        if edge.source not in target_to_sources[edge.target]:
            target_to_sources[edge.target].append(edge.source)
    clock_selectors = [
        {
            "id": target,
            "parent_options": sources,
        }
        for target, sources in target_to_sources.items()
        if len(sources) > 1
    ]

    dma_bindings = [
        {
            "peripheral": d.peripheral,
            "signal": d.signal,
            "request_id": d.request_value,
        }
        for d in dma_requests
    ]

    # Pins: aggregate AF rows per-pin.
    pin_to_afs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sig in signal_afs:
        pin_to_afs[sig.pin].append(
            {
                "af": sig.af_number,
                "peripheral": sig.peripheral,
                "signal": sig.signal,
            }
        )
    pins = [
        {"name": pin_name, "alternate_functions": afs}
        for pin_name, afs in sorted(pin_to_afs.items())
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
            "source_id": "modm-devices",
            "source_path": None,
            "patch_ids": [f"modm-devices@{provenance_sha}" if provenance_sha else "modm-devices"],
        },
        "clock_nodes": clock_nodes,
        "clock_selectors": clock_selectors,
        "dma_bindings": dma_bindings,
        "pins": pins,
    }


def _classify_clock_node(node_id: str) -> str:
    """Best-effort kind classification for modm clock node ids."""
    lower = node_id.lower()
    if lower.startswith("hsi") or lower.startswith("hse") or lower.startswith("lsi"):
        return "oscillator"
    if "pll" in lower:
        return "pll"
    if lower in {"sysclk", "hclk", "pclk"}:
        return "system-clock"
    return "internal-oscillator"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_modm_xml(request: ExtractionRequest) -> Path | None:
    """Look up the modm XML path from the request's source paths.

    * ``source_paths["modm-devices"]`` — direct path or root.
    * ``source_paths["modm-xml"]`` — direct path to the XML file.
    """
    if "modm-xml" in request.source_paths:
        return request.source_paths["modm-xml"]
    if "modm-devices" in request.source_paths:
        candidate = request.source_paths["modm-devices"]
        if candidate.is_file():
            return candidate
        # Try the conventional layout: devices/stm32/<family>/<device>.xml
        short_family = request.family.removeprefix("stm32")
        candidate_a = candidate / "devices" / "stm32" / short_family / f"{request.device}.xml"
        if candidate_a.exists():
            return candidate_a
        short_device = request.device.removeprefix("stm32")
        candidate_b = candidate / "devices" / "stm32" / short_family / f"{short_device}.xml"
        if candidate_b.exists():
            return candidate_b
    return None


# ---------------------------------------------------------------------------
# Extractor protocol adapter
# ---------------------------------------------------------------------------


@register_extractor(
    "modm-devices",
    # Synthetic family — this extractor does NOT win the resolver.
    # It's invoked explicitly by the merge engine / pipeline as a
    # secondary enrichment.
    families=(("__modm_secondary__", "__modm_secondary__"),),
)
class ModmEnrichmentExtractor:
    """modm-devices secondary EnrichmentExtractor."""

    extractor_id: str = "modm-devices"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        xml_path = _resolve_modm_xml(request)
        if xml_path is None or not xml_path.exists():
            available_keys = sorted(request.source_paths)
            raise ValueError(
                f"modm-devices extractor: cannot resolve XML for "
                f"{request.device}.  Pass --source modm-xml=<path> or "
                f"--source modm-devices=<modm-devices-checkout-root>.  "
                f"Got source keys: {available_keys}"
            )
        clock_edges, dma_requests, signal_afs = _parse_modm_xml(xml_path)
        payload = _modm_to_payload(
            device=request.device,
            family=request.family,
            vendor=request.vendor,
            clock_edges=clock_edges,
            dma_requests=dma_requests,
            signal_afs=signal_afs,
            provenance_sha=request.revision,
        )
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="modm-devices",
                source_path=str(xml_path),
                revision=request.revision,
            ),
            warnings=(
                "modm-devices is a secondary enrichment — "
                "compose with a primary extraction via "
                "alloy_data_extractor.merge.merge_payloads(...).",
            ),
        )


__all__ = [
    "ModmClockEdge",
    "ModmDmaRequest",
    "ModmEnrichmentExtractor",
    "ModmSignalAf",
]
