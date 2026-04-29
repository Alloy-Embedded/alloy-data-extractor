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

import re
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


# ---------------------------------------------------------------------------
# Register tree projection (Phase 1.1 follow-up).
#
# CMSIS-SVD's <peripheral><registers><register><fields><field> tree is
# the authoritative structural layout for every memory-mapped peripheral.
# Phase-1 STM32 extraction was previously missing this — the merge
# engine had nothing to merge for `registers` / `register_fields`,
# so re-emitted YAMLs lost the entire register inventory.
#
# This module projects the SVD register tree into two flat lists
# (`registers` and `register_fields`) shaped like the canonical
# `alloy-devices-yml` schema:
#
#   registers:
#     - register_id: register:<peri-lower>:<reg-lower>
#       peripheral: <PERI>
#       name: <REG>
#       offset_bytes: <int>
#       size_bits: <int>
#       access: read-only / write-only / read-write / write-once / …
#
#   register_fields:
#     - field_id: field:<peri-lower>:<reg-lower>:<field-lower>
#       register_id: register:<peri-lower>:<reg-lower>
#       peripheral: <PERI>
#       register_name: <REG>
#       name: <FIELD>
#       bit_offset: <int>
#       bit_width: <int>
#       access: read-only / write-only / read-write / write-once
#
# `derivedFrom`, `<dim>` arrays, `bitRange="[15:8]"`, and `<lsb>+<msb>`
# field positions are all resolved here.  Cluster blocks (<cluster>)
# are ignored for now — STM32 SVDs don't use them; vendors that do
# (NXP iMXRT) are handled by `nxp_mcux.py` which has its own walker.
# ---------------------------------------------------------------------------


_BIT_RANGE_RE = re.compile(r"\[\s*(?P<msb>\d+)\s*:\s*(?P<lsb>\d+)\s*\]")


def _parse_field_position(field: ET.Element) -> tuple[int | None, int | None]:
    """Resolve a SVD ``<field>``'s bit position from the three
    legal forms: ``bitOffset+bitWidth``, ``bitRange="[msb:lsb]"``,
    or ``lsb+msb``.  Returns ``(bit_offset, bit_width)`` or
    ``(None, None)`` when the field can't be located."""
    bit_offset = _parse_int(field.findtext("bitOffset"))
    bit_width = _parse_int(field.findtext("bitWidth"))
    if bit_offset is not None and bit_width is not None:
        return bit_offset, bit_width

    bit_range = _findtext(field, "bitRange")
    if bit_range:
        match = _BIT_RANGE_RE.match(bit_range)
        if match:
            msb = int(match.group("msb"))
            lsb = int(match.group("lsb"))
            return lsb, msb - lsb + 1

    lsb = _parse_int(field.findtext("lsb"))
    msb = _parse_int(field.findtext("msb"))
    if lsb is not None and msb is not None:
        return lsb, msb - lsb + 1

    return None, None


def _parse_dim_index(text: str | None, dim: int) -> list[str]:
    """Parse a SVD ``<dimIndex>`` body into the per-instance label.

    Two legal shapes:
    * ``"0-7"`` (range) → ``["0", "1", ..., "7"]``
    * ``"A,B,C,D"`` (csv) → ``["A", "B", "C", "D"]``
    Falls back to ``["0", "1", ..., dim-1]`` when the body is
    missing or unparseable.
    """
    if not text:
        return [str(i) for i in range(dim)]
    text = text.strip()
    if "-" in text and "," not in text:
        try:
            lo_s, hi_s = text.split("-", 1)
            lo = int(lo_s.strip())
            hi = int(hi_s.strip())
            return [str(i) for i in range(lo, hi + 1)]
        except ValueError:
            pass
    if "," in text:
        return [tok.strip() for tok in text.split(",") if tok.strip()]
    return [text]


def _expand_register_dim(register: ET.Element) -> list[dict[str, Any]]:
    """Return one row per ``<dim>`` instance.  When ``<dim>`` is
    absent or 1, returns a single entry equal to the register's
    own name + offset.

    Each row carries the resolved ``name`` (with ``%s`` replaced
    by the dimIndex token), ``offset``, ``size_bits``, and
    ``access`` strings — or ``None`` when the SVD doesn't supply
    one (the caller resolves inheritance from the parent
    peripheral).
    """
    base_name = _findtext(register, "name")
    base_offset = _parse_int(register.findtext("addressOffset"))
    if not base_name or base_offset is None:
        return []

    size = _parse_int(register.findtext("size"))
    access = _findtext(register, "access") or None

    dim = _parse_int(register.findtext("dim"))
    if dim is None or dim <= 1:
        return [
            {
                "name": base_name,
                "offset": base_offset,
                "size_bits": size,
                "access": access,
            }
        ]

    increment = _parse_int(register.findtext("dimIncrement")) or 0
    indexes = _parse_dim_index(register.findtext("dimIndex"), dim)
    if len(indexes) != dim:
        indexes = [str(i) for i in range(dim)]

    rows: list[dict[str, Any]] = []
    for i, index_label in enumerate(indexes):
        instance_name = base_name.replace("%s", index_label)
        rows.append(
            {
                "name": instance_name,
                "offset": base_offset + i * increment,
                "size_bits": size,
                "access": access,
            }
        )
    return rows


def _register_and_field_records(
    root: ET.Element,
) -> tuple[list[dict], list[dict]]:
    """Project the SVD register tree into flat ``registers`` +
    ``register_fields`` lists.  Resolves ``derivedFrom`` (registers
    from a base peripheral propagate to the derived one) and
    inherits access/size from the parent peripheral when the
    register itself doesn't override them.
    """
    peripherals_node = root.find("peripherals")
    if peripherals_node is None:
        return [], []

    # Index peripheral elements by name so we can resolve
    # derivedFrom to the base peripheral's <registers> block.
    peri_by_name: dict[str, ET.Element] = {}
    for peri in peripherals_node.findall("peripheral"):
        name = _findtext(peri, "name")
        if name:
            peri_by_name[name] = peri

    registers_out: list[dict] = []
    fields_out: list[dict] = []

    for peri in peripherals_node.findall("peripheral"):
        peri_name = _findtext(peri, "name")
        if not peri_name:
            continue

        # Resolve derivedFrom: walk to the base peripheral whose
        # <registers> block we share.  STM32 SVDs commonly
        # `derivedFrom="USART1"` for USART2..N — the latter inherit
        # the entire register tree.
        register_source = peri
        derived_from = peri.attrib.get("derivedFrom")
        if derived_from and derived_from in peri_by_name:
            register_source = peri_by_name[derived_from]

        # Defaults that registers/fields can fall back to when their
        # own SVD entry omits the value.
        default_access = (
            _findtext(peri, "access")
            or _findtext(register_source, "access")
            or None
        )
        default_size = (
            _parse_int(peri.findtext("size"))
            or _parse_int(register_source.findtext("size"))
            or 32
        )

        registers_node = register_source.find("registers")
        if registers_node is None:
            continue

        peri_lower = peri_name.lower()
        for register in registers_node.findall("register"):
            for instance in _expand_register_dim(register):
                reg_name = instance["name"]
                reg_offset = instance["offset"]
                reg_size = instance["size_bits"] or default_size
                reg_access = instance["access"] or default_access or "read-write"
                reg_lower = reg_name.lower()
                register_id = f"register:{peri_lower}:{reg_lower}"

                registers_out.append(
                    {
                        "register_id": register_id,
                        "peripheral": peri_name,
                        "name": reg_name,
                        "offset_bytes": reg_offset,
                        "size_bits": reg_size,
                        "access": reg_access,
                    }
                )

                fields_node = register.find("fields")
                if fields_node is None:
                    continue
                for field in fields_node.findall("field"):
                    field_name = _findtext(field, "name")
                    bit_offset, bit_width = _parse_field_position(field)
                    if not field_name or bit_offset is None or bit_width is None:
                        continue
                    field_access = (
                        _findtext(field, "access") or reg_access
                    )
                    fields_out.append(
                        {
                            "field_id": (
                                f"field:{peri_lower}:{reg_lower}:"
                                f"{field_name.lower()}"
                            ),
                            "register_id": register_id,
                            "peripheral": peri_name,
                            "register_name": reg_name,
                            "name": field_name,
                            "bit_offset": bit_offset,
                            "bit_width": bit_width,
                            "access": field_access,
                        }
                    )

    # Sort deterministically — by (peripheral, register offset,
    # name) for registers; (peripheral, register, bit_offset) for
    # fields.  Matches the canonical YAML's existing ordering.
    registers_out.sort(
        key=lambda r: (r["peripheral"].lower(), r["offset_bytes"], r["name"].lower())
    )
    fields_out.sort(
        key=lambda f: (
            f["peripheral"].lower(),
            f["register_name"].lower(),
            f["bit_offset"],
        )
    )
    return registers_out, fields_out


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
    registers, register_fields = _register_and_field_records(root)

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
        "registers": registers,
        "register_fields": register_fields,
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
    #
    # The community RISC-V vendors (gigadevice, bouffalo, wch,
    # kendryte, allwinner) ride on the CMSIS-SVD adapter via
    # `add-riscv-community-svd-extractor` (Phase 3.4) — they
    # publish CMSIS-SVD-compatible XML and need nothing more
    # than this registration entry.
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
