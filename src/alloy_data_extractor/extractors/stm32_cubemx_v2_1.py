"""STM32CubeMX → v2.1 enrichment extractor.

Reads the CubeMX MCU database (the ``db/`` tree shipped inside
``STM32CubeMX.app``) and produces a v2.1 enrichment payload
covering:

* ``clock.domains[].select_register`` / ``prescaler_register`` /
  ``auxsrc_register`` — encoded source / divider muxes with the
  full ``encoding`` map (delta 12 of the v2.1 audit).
* ``clock.oscillators`` — declared sources with declared default
  frequencies.
* ``peripherals[<dma>].dma_requests`` — the per-peripheral DMA
  request matrix (signal → request value) extracted from the
  per-IP DMA Modes XML.
* ``peripherals[<id>].ip_version`` — same as open-pin-data,
  exposed here so the merge engine can fall back when only the
  CubeMX DB is available.

The extractor accepts the chip XML by name (``STM32G030F6Px.xml``)
and the DB root.  On macOS the default DB root is
``/Applications/STMicroelectronics/STM32CubeMX.app/Contents/Resources/db``;
on Linux it's ``~/STM32CubeMX/db`` (configurable via the
``--cubemx-db`` flag in the bulk-extract scripts).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------


def _strip_ns(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith("{"):
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _attr(node: ET.Element, key: str, default: str = "") -> str:
    return node.get(key, default) or default


# ---------------------------------------------------------------------------
# Well-known ST RCC encodings.
# ---------------------------------------------------------------------------
#
# CubeMX clock-tree XMLs declare the source list per multiplexor
# but NOT the integer encoding — the value is implicit in the
# RCC register field ordering, which is documented in each
# family's reference manual and is largely stable across F0/F1/
# F4/G0/G4/H7.  Hard-coding the well-known mappings here lets the
# extractor surface a complete `select_register` block without
# parsing every IP-version's RCC modes XML.

# Source encoding tables, keyed by multiplexor id (the `<Element
# id="..."/>` value in the clock-tree XML).
_RCC_SOURCE_ENCODINGS: dict[str, dict[str, Any]] = {
    "SYSCLKSource": {
        "reg": "RCC.CFGR", "field": "SW",
        "encoding": {"hsi": 0, "hse": 1, "pll_main": 2, "pllrclk": 2,
                      "lsi": 3, "lse": 3, "hsi48": 3},
    },
    "PLLSource": {
        "reg": "RCC.PLLCFGR", "field": "PLLSRC",
        "encoding": {"none": 0, "msi": 1, "hsi": 2, "hse": 3,
                      "pll_hsi": 2, "pll_hse": 3},
    },
    "MCOMult": {
        "reg": "RCC.CFGR", "field": "MCOSEL",
        "encoding": {"none": 0, "sysclk": 1, "hsi48": 2, "hsi": 3,
                      "hse": 4, "pll_main": 5, "lsi": 6, "lse": 7},
    },
    "USART1Mult": {
        "reg": "RCC.CCIPR", "field": "USART1SEL",
        "encoding": {"pclk": 0, "sysclk": 1, "hsi": 2, "lse": 3},
    },
    "USART2Mult": {
        "reg": "RCC.CCIPR", "field": "USART2SEL",
        "encoding": {"pclk": 0, "sysclk": 1, "hsi": 2, "lse": 3},
    },
    "I2C1Mult": {
        "reg": "RCC.CCIPR", "field": "I2C1SEL",
        "encoding": {"pclk": 0, "sysclk": 1, "hsi": 2},
    },
    "ADCMult": {
        "reg": "RCC.CCIPR", "field": "ADCSEL",
        "encoding": {"sysclk": 0, "pllpclk": 1, "hsi": 2},
    },
    "RTCSource": {
        "reg": "RCC.BDCR", "field": "RTCSEL",
        "encoding": {"none": 0, "lse": 1, "lsi": 2, "hse": 3},
    },
    "LPTIM1Mult": {
        "reg": "RCC.CCIPR", "field": "LPTIM1SEL",
        "encoding": {"pclk": 0, "lsi": 1, "hsi": 2, "lse": 3},
    },
    "LPTIM2Mult": {
        "reg": "RCC.CCIPR", "field": "LPTIM2SEL",
        "encoding": {"pclk": 0, "lsi": 1, "hsi": 2, "lse": 3},
    },
    "LPUART1Mult": {
        "reg": "RCC.CCIPR", "field": "LPUART1SEL",
        "encoding": {"pclk": 0, "sysclk": 1, "hsi": 2, "lse": 3},
    },
}


# Prescaler encoding tables (devisor elements).
_RCC_PRESCALER_ENCODINGS: dict[str, dict[str, Any]] = {
    "AHBPrescaler": {
        "reg": "RCC.CFGR", "field": "HPRE",
        "encoding": {1: 0, 2: 8, 4: 9, 8: 10, 16: 11,
                      64: 12, 128: 13, 256: 14, 512: 15},
    },
    "APBPrescaler": {
        "reg": "RCC.CFGR", "field": "PPRE",
        "encoding": {1: 0, 2: 4, 4: 5, 8: 6, 16: 7},
    },
    "APB1Prescaler": {
        "reg": "RCC.CFGR", "field": "PPRE1",
        "encoding": {1: 0, 2: 4, 4: 5, 8: 6, 16: 7},
    },
    "APB2Prescaler": {
        "reg": "RCC.CFGR", "field": "PPRE2",
        "encoding": {1: 0, 2: 4, 4: 5, 8: 6, 16: 7},
    },
    "HSEDivPLL": {
        "reg": "RCC.PLLCFGR", "field": "PLLM",
        "encoding": {n: n - 1 for n in range(1, 17)},
    },
    "HSISYS": {
        "reg": "RCC.CR", "field": "HSIDIV",
        "encoding": {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7},
    },
}


# Default frequencies for the standard oscillator sources, when the
# clock-tree XML doesn't carry the value.  G0/G4/F0/F4 all share
# these.
_DEFAULT_OSC_FREQS: dict[str, tuple[str, str]] = {
    "HSIRC":   ("16MHz", "rc-internal"),
    "HSI":     ("16MHz", "rc-internal"),
    "HSI48":   ("48MHz", "rc-internal"),
    "HSEOSC":  ("0Hz",   "crystal-external"),
    "HSE":     ("0Hz",   "crystal-external"),
    "LSIRC":   ("32kHz", "rc-internal"),
    "LSI":     ("32kHz", "rc-internal"),
    "LSEOSC":  ("32.768kHz", "crystal-external"),
    "LSE":     ("32.768kHz", "crystal-external"),
    "MSI":     ("4MHz",  "rc-internal"),
    "I2S_CKIN":("0Hz",   "synthesised"),
}


# Map a source signal id (clock-tree XML's `<Input signalId="HSI"/>`)
# to a v2.1 oscillator id (lowercase, normalised).
_SIGNAL_TO_OSC_ID: dict[str, str] = {
    "HSI":  "hsi",  "HSIRC":  "hsi",
    "HSE":  "hse",  "HSEOSC": "hse",
    "LSI":  "lsi",  "LSIRC":  "lsi",
    "LSE":  "lse",  "LSEOSC": "lse",
    "HSI48": "hsi48",
    "MSI":   "msi",
    "PLLSRC": "pll_main",
    "PLLRCLK": "pll_main",
    "PLLPCLK": "pll_p",
    "PLLQCLK": "pll_q",
    "SysClkSource": "sysclk",
    "SYSCLK": "sysclk",
    "HSISYSCLK": "sysclk_pre",
}


def _normalise_source(signal: str) -> str:
    """Lowercase + map well-known signal names to canonical ids."""
    s = signal.strip()
    return _SIGNAL_TO_OSC_ID.get(s, s.lower())


@dataclass(slots=True)
class _ClockNode:
    id: str
    type: str           # "fixedSource", "multiplexor", "devisor", "activeOutput", …
    inputs:  list[tuple[str, str | None]]    # (signal, refValue)
    outputs: list[str]                        # downstream node ids


def _walk_clock_tree(xml_path: Path) -> dict[str, _ClockNode]:
    """Parse a CubeMX clock-tree XML into a {node_id → _ClockNode} dict."""
    if not xml_path.is_file():
        return {}
    root = _strip_ns(ET.parse(xml_path))
    nodes: dict[str, _ClockNode] = {}
    for elem in root.iter("Element"):
        nid = _attr(elem, "id")
        if not nid:
            continue
        ntype = _attr(elem, "type")
        inputs: list[tuple[str, str | None]] = []
        outputs: list[str] = []
        for child in elem:
            tag = child.tag.split("}", 1)[-1]
            if tag == "Input":
                inputs.append((_attr(child, "signalId"),
                                child.get("refValue")))
            elif tag == "Output":
                outputs.append(_attr(child, "to"))
        nodes[nid] = _ClockNode(id=nid, type=ntype,
                                 inputs=inputs, outputs=outputs)
    return nodes


def _build_oscillator_block(nodes: dict[str, _ClockNode]) -> dict[str, dict[str, Any]]:
    """Synthesise the oscillator dict from `fixedSource` nodes + the
    well-known frequency table."""
    out: dict[str, dict[str, Any]] = {}
    for nid, node in nodes.items():
        if node.type != "fixedSource":
            continue
        osc_id = _SIGNAL_TO_OSC_ID.get(nid, nid.lower())
        if osc_id in out:
            continue
        freq, kind = _DEFAULT_OSC_FREQS.get(nid, ("0Hz", "rc-internal"))
        oscillator: dict[str, Any] = {"freq": freq, "kind": kind}
        if "external" in kind:
            oscillator["optional"] = True
        out[osc_id] = oscillator
    if not out:
        # Defensive — every chip should have at least HSI.
        out["hsi"] = {"freq": "16MHz", "kind": "rc-internal"}
    return out


def _build_clock_domains(nodes: dict[str, _ClockNode]) -> list[dict[str, Any]]:
    """Synthesise v2.1 clock.domains[] from the clock-tree node graph."""
    out: list[dict[str, Any]] = []

    for nid, node in nodes.items():
        # Multiplexors → source-select domains.
        if node.type == "multiplexor":
            sources = [_normalise_source(sig) for sig, _ in node.inputs]
            sources = list(dict.fromkeys(sources))   # dedupe, keep order
            if not sources:
                continue
            domain: dict[str, Any] = {
                "id":      nid.lower().replace("source", "_source"),
                "sources": sources,
            }
            select = _RCC_SOURCE_ENCODINGS.get(nid)
            if select is not None:
                # Build encoding for the sources actually present on this chip.
                encoded: dict[str, int] = {}
                for src in sources:
                    if src in select["encoding"]:
                        encoded[src] = select["encoding"][src]
                if encoded:
                    domain["select_register"] = {
                        "reg":   select["reg"],
                        "field": select["field"],
                        "encoding": encoded,
                    }
            out.append(domain)
        elif node.type == "devisor":
            # Devisors → prescaler chains; record `source` (single
            # input) + the prescaler encoding when known.
            sources = [_normalise_source(sig) for sig, _ in node.inputs]
            domain = {"id": nid.lower()}
            if sources:
                domain["source"] = sources[0]
            presc = _RCC_PRESCALER_ENCODINGS.get(nid)
            if presc is not None:
                domain["prescalers"] = list(presc["encoding"].keys())
                domain["prescaler_register"] = {
                    "reg":   presc["reg"],
                    "field": presc["field"],
                    "encoding": {str(k): v for k, v in presc["encoding"].items()},
                }
            out.append(domain)
    return out


# ---------------------------------------------------------------------------
# DMA request matrix
# ---------------------------------------------------------------------------


def _read_dma_modes(db_root: Path, dma_version: str) -> list[dict[str, Any]]:
    """Return the per-peripheral DMA-request rows for a given
    DMA IP version (e.g. ``STM32G041_dma1_v1_3``)."""
    candidate = db_root / "mcu" / "IP" / f"DMA-{dma_version}_Modes.xml"
    if not candidate.is_file():
        # Search by glob — version names sometimes mismatch.
        candidates = sorted((db_root / "mcu" / "IP").glob(f"DMA-*{dma_version}*Modes.xml"))
        if not candidates:
            return []
        candidate = candidates[0]
    root = _strip_ns(ET.parse(candidate))
    rows: list[dict[str, Any]] = []
    for ref in root.iter("RefParameter"):
        if _attr(ref, "Name") != "Request":
            continue
        for i, val in enumerate(ref.iter("PossibleValue")):
            comment = _attr(val, "Comment")
            value = _attr(val, "Value")
            if not value or not value.startswith("DMA_REQUEST_"):
                continue
            request_id = value.replace("DMA_REQUEST_", "")
            # Skip non-peripheral requests (MEM2MEM, GENERATOR0..3, …).
            if request_id in {"MEM2MEM"} or request_id.startswith("GENERATOR"):
                continue
            # Heuristic: split by underscore — ``USART2_TX`` →
            # peripheral=``usart2``, signal=``tx``.
            parts = request_id.split("_", 1)
            peripheral = parts[0].lower()
            signal = parts[1].lower() if len(parts) > 1 else ""
            rows.append({
                "peripheral":    peripheral,
                "signal":        signal,
                "request_value": i,
                "request_id":    request_id,
                "label":         comment or request_id,
            })
        break  # only the first <RefParameter Name="Request"/> matters
    return rows


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    db_root: Path,
    chip_xml: Path | None = None,
) -> dict[str, Any]:
    """Read the CubeMX chip XML + dependent IP-version + clock-tree
    XMLs, return a v2.1 enrichment payload.

    ``chip_xml`` defaults to ``<db_root>/mcu/<RefName>.xml`` when the
    caller doesn't pass an explicit path.
    """
    db_root = db_root.resolve()
    if chip_xml is None:
        chip_xml = db_root / "mcu" / f"{device}.xml"
        if not chip_xml.is_file():
            # Try variant name normalisations (the DB uses e.g.
            # ``STM32G030F6Px.xml`` not ``stm32g030f6.xml``).
            matches = sorted((db_root / "mcu").glob(
                f"{device.upper()[:9]}*.xml"))
            if matches:
                chip_xml = matches[0]
    if not chip_xml.is_file():
        raise FileNotFoundError(f"CubeMX chip XML not found: {chip_xml}")

    root = _strip_ns(ET.parse(chip_xml))

    # ---- IP versions + DMA discovery ----
    ip_versions: dict[str, str] = {}
    dma_versions: list[str] = []
    for ip in root.iter("IP"):
        instance = _attr(ip, "InstanceName")
        version = _attr(ip, "Version")
        name = _attr(ip, "Name")
        if instance and version:
            ip_versions[instance.lower()] = version
        if name == "DMA" and version:
            dma_versions.append(version)

    # ---- Clock tree ----
    clock_tree_id = _attr(root, "ClockTree")
    clock_tree_xml = db_root / "plugins" / "clock" / f"{clock_tree_id}.xml"
    nodes = _walk_clock_tree(clock_tree_xml)
    oscillators = _build_oscillator_block(nodes)
    domains = _build_clock_domains(nodes)
    if not domains:
        # Fallback so the schema's required `domains` is non-empty.
        domains = [{"id": "sysclk",
                     "sources": list(oscillators.keys()) or ["hsi"]}]

    # ---- DMA request matrix → per-peripheral dma_requests ----
    dma_rows: list[dict[str, Any]] = []
    for v in dma_versions:
        dma_rows.extend(_read_dma_modes(db_root, v))

    # ---- Peripherals enrichment ----
    peripherals: list[dict[str, Any]] = []
    emitted: set[str] = set()

    # Per-instance DMA matrix bundle (collect rows by peripheral id
    # so each peripheral can carry its own ``dma_requests``).
    by_per: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dma_rows:
        # Both digit-suffixed id and the digit-stripped alias.
        per_id = row["peripheral"]
        by_per[per_id].append(row)
        stripped = per_id.rstrip("0123456789")
        if stripped and stripped != per_id:
            by_per[stripped].append(row)

    # Emit one row per IP-version peripheral.
    for instance, version in sorted(ip_versions.items()):
        candidate_ids = [instance]
        stripped = instance.rstrip("0123456789")
        if stripped and stripped != instance:
            candidate_ids.append(stripped)
        for cid in candidate_ids:
            if cid in emitted:
                continue
            emitted.add(cid)
            row: dict[str, Any] = {
                "id":         cid,
                "template":   "unknown",   # primary's template wins
                "ip_version": version,
            }
            if cid in by_per:
                row["dma_requests"] = [
                    {"signal": r["signal"] or "default",
                     "request_value": r["request_value"],
                     "request_id":    r["request_id"]}
                    for r in by_per[cid]
                ]
            peripherals.append(row)

    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {
            # Schema requires lowercased device ids (a-z0-9_-); CubeMX
            # names are mixed-case (``STM32G030F6Px``) — normalise.
            "vendor": vendor, "family": family, "device": device.lower(),
            "core":   {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
        },
        "provenance": {
            "primary":  f"stm32-cubemx:{chip_xml.name}",
            "authored": "auto",
            "notes":    "Extracted from STM32CubeMX MCU database.",
        },
        "memory": [
            {"id": "flash", "base": "0x00000000", "size": "1B",
             "access": "rx", "role": "extractor-placeholder"},
        ],
        "clock": {
            "oscillators": oscillators,
            "domains":     domains,
        },
        "peripherals": peripherals,
        "pinout":      [{"signal": "RESET"}],
    }
    return payload


__all__ = ["extract_device"]
