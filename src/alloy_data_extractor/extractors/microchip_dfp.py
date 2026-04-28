"""Microchip DFP/ATDF extractor — `migrate-microchip-dfp-extractor`
(Phase 1.2).

Reads Microchip ATDF (Atmel Tools Device File) XML and projects
peripherals + interrupts into a canonical-IR-shaped payload.

ATDF structure (relevant subset):

```
<avr-tools-device-file>
  <devices>
    <device architecture="CORTEX-M7" family="SAME" name="ATSAME70Q21B">
      <peripherals>
        <module name="UART">
          <instance name="UART0">
            <register-group name="UART0" address-space="base" offset="0x400E0800"/>
          </instance>
        </module>
      </peripherals>
      <interrupts>
        <interrupt index="..." name="..." module-instance="..."/>
      </interrupts>
    </device>
  </devices>
</avr-tools-device-file>
```

The current implementation is intentionally narrow: peripherals
(name + base) + interrupts (line + name + peripheral).  Full
register tree + bitfield enumerations are deferred to a follow-up
because ATDF carries them in a *very* different shape from
CMSIS-SVD and porting that part is the bulk of
``alloy-codegen/src/alloy_codegen/sources/microchip_dfp.py``.

Codegen-side ``_build_microchip_device_ir`` continues to handle
patches + register layout until that follow-up lands.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)


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


def _atdf_core_to_canonical(atdf_arch: str | None) -> str:
    """Map ATDF ``<device architecture="...">`` to canonical core name."""
    if not atdf_arch:
        return ""
    upper = atdf_arch.upper().strip()
    table = {
        "CORTEX-M0": "cortex-m0",
        "CORTEX-M0PLUS": "cortex-m0plus",
        "CORTEX-M0+": "cortex-m0plus",
        "CORTEX-M3": "cortex-m3",
        "CORTEX-M4": "cortex-m4",
        "CORTEX-M4F": "cortex-m4f",
        "CORTEX-M7": "cortex-m7",
        "CORTEX-M7F": "cortex-m7f",
        "AVR8": "avr8",
        "AVR8X": "avr8",
        "PIC12": "pic12f",
        "PIC12F": "pic12f",
        "PIC16": "pic16f",
        "PIC16F": "pic16f",
        "PIC18": "pic18",
        "PIC24": "pic24f",
        "PIC24F": "pic24f",
        "DSPIC33": "dspic33",
        "PIC32MX": "pic32mx",
        "PIC32MZ": "pic32mz",
        "PIC32MK": "pic32mk",
    }
    return table.get(upper, upper.lower())


def _peripheral_records(device: ET.Element) -> tuple[list[dict], list[dict]]:
    peripherals: list[dict] = []
    interrupts: list[dict] = []
    seen_irq_lines: set[int] = set()

    peripherals_root = device.find("peripherals")
    if peripherals_root is not None:
        for module in peripherals_root.findall("module"):
            for instance in module.findall("instance"):
                instance_name = instance.get("name")
                if not instance_name:
                    continue
                # First register-group's offset is the instance base.
                register_group = instance.find("register-group")
                if register_group is None:
                    continue
                base = _parse_int(register_group.get("offset"))
                if base is None:
                    continue
                peripherals.append(
                    {
                        "name": instance_name,
                        "base_address": base,
                        "description": module.get("name", ""),
                    }
                )

    interrupts_root = device.find("interrupts")
    if interrupts_root is not None:
        for irq in interrupts_root.findall("interrupt"):
            line = _parse_int(irq.get("index"))
            name = irq.get("name") or ""
            mod_inst = irq.get("module-instance") or name.split("_", 1)[0]
            if line is None or line in seen_irq_lines:
                continue
            interrupts.append(
                {
                    "name": name,
                    "line": line,
                    "peripheral": mod_inst,
                }
            )
            seen_irq_lines.add(line)

    peripherals.sort(key=lambda r: (r["base_address"], r["name"]))
    interrupts.sort(key=lambda r: (r["line"], r["name"]))
    return peripherals, interrupts


def _resolve_atdf_path(request: ExtractionRequest) -> Path | None:
    """Resolve the ATDF path from the request's source paths.

    * ``source_paths["atdf"]`` — direct path.
    * ``source_paths["microchip-dfp"]`` — root of the DFP cache;
      the extractor walks ``**/<UPPER_DEVICE>.atdf``.
    """
    if "atdf" in request.source_paths:
        return request.source_paths["atdf"]
    if "microchip-dfp" in request.source_paths:
        upper = request.device.upper()
        for atdf in request.source_paths["microchip-dfp"].rglob(f"{upper}.atdf"):
            return atdf
    return None


@register_extractor(
    "microchip-dfp",
    families=(
        ("microchip", "avr-da"),
        ("microchip", "same70"),
    ),
)
class MicrochipDfpExtractor:
    """Microchip DFP/ATDF extractor — Phase 1.2 implementation."""

    extractor_id: str = "microchip-dfp"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        atdf_path = _resolve_atdf_path(request)
        if atdf_path is None or not atdf_path.exists():
            available_keys = sorted(request.source_paths)
            raise ValueError(
                f"microchip-dfp extractor: cannot resolve ATDF for "
                f"{request.device}.  Pass --source atdf=<path> or "
                f"--source microchip-dfp=<dfp-cache-root>.  "
                f"Got source keys: {available_keys}"
            )
        root = ET.parse(atdf_path).getroot()
        device = root.find(".//device")
        if device is None:
            raise ValueError(
                f"microchip-dfp extractor: ATDF at {atdf_path} has no <device> element."
            )
        core = _atdf_core_to_canonical(device.get("architecture"))
        peripherals, interrupts = _peripheral_records(device)

        payload: dict[str, Any] = {
            "schema_version": "1.2.0",
            "identity": {
                "vendor": request.vendor,
                "family": request.family,
                "device": request.device,
                "package": "",
                "core": core,
                "summary": f"Admitted via Microchip DFP/ATDF ({atdf_path.name}).",
            },
            "provenance": {
                "source_id": "microchip-dfp",
                "source_path": str(atdf_path),
                "patch_ids": [],
            },
            "memories": [],
            "peripherals": peripherals,
            "interrupts": interrupts,
        }

        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="microchip-dfp",
                source_path=str(atdf_path),
                revision=request.revision,
            ),
            warnings=(
                "Microchip DFP extractor: register tree + bitfield "
                "enumerated values not yet emitted — Phase 1.2 "
                "follow-up ports the full ATDF parser.",
            ),
        )


__all__ = ["MicrochipDfpExtractor"]
