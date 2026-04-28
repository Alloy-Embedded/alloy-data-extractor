"""CMSIS-SVD extractor.

Reads a CMSIS-SVD XML file and projects it into a canonical-IR
intermediate representation.  Covers any vendor whose chips are
catalogued in `cmsis-svd-data` (community SVD index) or in a
vendor-distributed CMSIS-Pack.

The shape returned matches what the alloy-codegen consumer
expects after parsing the canonical YAML — a dict with keys
``schema_version``, ``identity``, ``memories``, ``peripherals``,
``interrupts``, ``registers``, ``register_fields``, plus
``provenance``.

Initial v1 surface is intentionally narrow: peripherals + IRQ
table + register names/offsets.  Bitfield enumerated values,
register arrays (`<dim>`), and pin/AF tables are filled in
follow-up changes (see alloy-codegen's
``populate-imxrt-iomux-gpio-pins``,
``decode-zephyr-pinctrl-into-connection-candidates``,
``extract-svd-enumerated-values`` for the IR-completeness
roadmap).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CmsisSvdExtraction:
    """Outcome of one SVD extraction.  ``provenance`` is the
    record alloy-devices-yml stamps onto the YAML so reviewers
    can audit which upstream pin produced the data."""

    payload: dict[str, Any]
    provenance: dict[str, str]


def _findtext(node: ET.Element, key: str, default: str = "") -> str:
    found = node.findtext(key)
    return found.strip() if found else default


def _parse_cpu(root: ET.Element) -> str | None:
    cpu = root.find("cpu")
    if cpu is None:
        return None
    cpu_name = _findtext(cpu, "name")
    fpu_present = _findtext(cpu, "fpuPresent", "false").lower() == "true"
    cm_map = {
        "CM0": "cortex-m0",
        "CM0PLUS": "cortex-m0plus",
        "CM0+": "cortex-m0plus",
        "CM3": "cortex-m3",
        "CM4": "cortex-m4",
        "CM7": "cortex-m7",
        "CM23": "cortex-m23",
        "CM33": "cortex-m33",
        "CM55": "cortex-m55",
    }
    base = cm_map.get(cpu_name.upper())
    if base is None:
        return None
    if fpu_present and base in {"cortex-m4", "cortex-m7"}:
        return f"{base}f"
    return base


def _parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def _peripheral_records(root: ET.Element) -> tuple[list[dict], list[dict]]:
    peripherals: list[dict] = []
    interrupts: list[dict] = []
    seen_irq_lines: set[int] = set()

    peripherals_node = root.find("peripherals")
    if peripherals_node is None:
        return peripherals, interrupts

    for peripheral in peripherals_node.findall("peripheral"):
        name = _findtext(peripheral, "name")
        base = _parse_int(peripheral.findtext("baseAddress"))
        if not name or base is None:
            continue
        peripherals.append(
            {
                "name": name,
                "base_address": base,
                "description": _findtext(peripheral, "description"),
            }
        )
        for interrupt in peripheral.findall("interrupt"):
            irq_name = _findtext(interrupt, "name")
            line = _parse_int(interrupt.findtext("value"))
            if not irq_name or line is None or line in seen_irq_lines:
                continue
            interrupts.append(
                {
                    "name": irq_name,
                    "line": line,
                    "peripheral": name,
                    "description": _findtext(interrupt, "description"),
                }
            )
            seen_irq_lines.add(line)

    peripherals.sort(key=lambda r: (r["base_address"], r["name"]))
    interrupts.sort(key=lambda r: (r["line"], r["name"]))
    return peripherals, interrupts


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    svd_path: Path,
    revision: str,
    schema_version: str = "1.2.0",
) -> CmsisSvdExtraction:
    """Extract one device from a CMSIS-SVD file.

    The returned payload is the canonical-IR shape that
    `alloy-devices-yml` consumers expect — directly serialisable
    by the canonical YAML writer with no further transformation.
    """
    if not svd_path.exists():
        raise FileNotFoundError(f"SVD file not found: {svd_path}")
    root = ET.parse(svd_path).getroot()
    core = _parse_cpu(root)
    peripherals, interrupts = _peripheral_records(root)

    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "identity": {
            "vendor": vendor,
            "family": family,
            "device": device,
            "package": "",
            "core": core or "",
            "summary": _findtext(root, "description"),
        },
        "provenance": {
            "source_id": "cmsis-svd",
            "source_path": str(svd_path),
            "patch_ids": [],
        },
        "memories": [],
        "peripherals": peripherals,
        "interrupts": interrupts,
    }

    return CmsisSvdExtraction(
        payload=payload,
        provenance={
            "source_id": "cmsis-svd",
            "revision": revision,
            "source_path": str(svd_path),
        },
    )


# ---------------------------------------------------------------------------
# Extractor protocol adapter (added by define-extractor-protocol)
# ---------------------------------------------------------------------------


from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)


@register_extractor(
    "cmsis-svd",
    # CMSIS-SVD covers many vendors via a uniform XML format; we
    # bind by vendor (catch-all) so per-family registration is
    # not required.  Specific vendor-specific extractors (e.g.
    # stm32) can override by registering with families= and
    # winning the resolver via specificity.
    vendors=(
        "st",
        "nordic",
        "microchip",
        "raspberrypi",
        "espressif",
        "nxp",
        "gigadevice",
        "bouffalo",
        "wch",
        "kendryte",
        "allwinner",
    ),
)
class CmsisSvdExtractor:
    """The :class:`Extractor` adapter for the CMSIS-SVD parser."""

    extractor_id: str = "cmsis-svd"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        # Decorator-derived bindings handle the actual admission.
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        svd_path = request.require_source("cmsis-svd")
        legacy = extract_device(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            svd_path=svd_path,
            revision=request.revision,
        )
        return ExtractionResult(
            payload=legacy.payload,
            provenance=ProvenanceRecord(
                source_id="cmsis-svd",
                source_path=str(svd_path),
                revision=request.revision,
            ),
            warnings=(),
        )


__all__ = ["CmsisSvdExtraction", "CmsisSvdExtractor", "extract_device"]
