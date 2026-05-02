"""STM32 open-pin-data → v2.1 secondary enrichment extractor.

Reads STMicroelectronics' STM32_open_pin_data XMLs (one per chip
package variant — e.g. ``STM32G030F6Px.xml`` for the TSSOP-20
package).  Produces an enrichment payload that overlays:

* ``identity.package`` — package code (e.g. ``TSSOP20``).
* ``peripherals[<id>].ip_version`` — per-instance IP version
  (e.g. ``aditf4_v3_0_G0_Cube`` for ADC).
* ``peripherals[<id>].pin_options`` — per-signal candidate pin lists
  derived from the ``<Pin><Signal Name="..._..."/></Pin>`` table.
* ``pinout`` — per-package pin list with silk-screen position.

Output is a primary payload in v2.1 shape **but flagged as
``provenance.primary = "stm32-open-pin-data"``** so the merge
engine treats it as an enrichment, never as the source-of-truth
for register layout.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


# Open-pin-data XMLs declare the (dummy) namespace
# ``http://dummy.com``.  Strip it from element tags so iter() works
# with bare names.
def _strip_namespace(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    for elem in root.iter():
        if elem.tag.startswith("{"):
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _attr(node: ET.Element, key: str, default: str = "") -> str:
    return node.get(key, default) or default


def _parse_int(text: str) -> int | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


# Signal naming convention: ``<INSTANCE>_<SIGNAL>``.
# Examples: USART2_TX, SPI1_MOSI, I2C1_SDA, TIM3_CH1, ADC1_IN5,
# TIM16_BKIN, USART1_RTS_DE.
#
# We split on the first underscore — the prefix is the instance name
# (lowercased), the suffix is the signal name (lowercased).
_SIGNAL_RE = re.compile(r"^([A-Z][A-Z0-9]*)_(.+)$")


def _split_signal(signal_name: str) -> tuple[str, str] | None:
    """``"USART2_TX"`` → ``("usart2", "tx")``.  Returns None when
    the signal doesn't fit the convention (e.g. plain
    ``GPIO_Output``)."""
    match = _SIGNAL_RE.match(signal_name)
    if not match:
        return None
    instance, signal = match.groups()
    return instance.lower(), signal.lower()


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    xml_path: Path,
) -> dict[str, Any]:
    """Read one open-pin-data XML and emit a v2.1 enrichment payload."""
    if not xml_path.exists():
        raise FileNotFoundError(f"Open-pin-data XML not found: {xml_path}")
    root = _strip_namespace(ET.parse(xml_path))

    # ---------- identity / package ----------
    package_raw = _attr(root, "Package").lower()

    # ---------- IP versions ----------
    ip_versions: dict[str, str] = {}
    for ip in root.iter("IP"):
        instance = _attr(ip, "InstanceName")
        version = _attr(ip, "Version")
        if instance and version:
            ip_versions[instance.lower()] = version

    # ---------- per-pin signal map ----------
    # pinout: list of per-pin entries (silk-screen ordered)
    # peripheral_pin_options[<inst_id>][<signal>] -> list of pins
    pinout_rows: list[dict[str, Any]] = []
    peripheral_pin_options: dict[str, dict[str, list[dict[str, Any]]]] = (
        defaultdict(lambda: defaultdict(list))
    )

    for pin in root.iter("Pin"):
        pin_name = _attr(pin, "Name")
        position = _parse_int(_attr(pin, "Position"))
        pin_type = _attr(pin, "Type")
        if not pin_name:
            continue
        # Skip raw type-only entries (e.g. NC); keep power + bonded I/O.
        row: dict[str, Any] = {"signal": pin_name}
        if position is not None and position >= 1:
            row["pin"] = position
        # Power / reset / boot constraints.
        upper_name = pin_name.upper()
        constraints: list[str] = []
        if pin_type.lower() == "power":
            constraints.append("power")
        if upper_name in {"NRST", "RESET"}:
            constraints.append("reset")
        if upper_name == "BOOT0":
            constraints.append("boot")
        if upper_name.startswith("VBAT"):
            constraints.append("power")
        if constraints:
            row["constraints"] = constraints
        pinout_rows.append(row)

        # Walk the signals declared on this pin.
        for sig in pin.iter("Signal"):
            sig_name = _attr(sig, "Name")
            split = _split_signal(sig_name)
            if split is None:
                continue
            instance, signal = split
            # Build the candidate row.
            candidate: dict[str, Any] = {"pin": pin_name}
            peripheral_pin_options[instance][signal].append(candidate)

    # ---------- compose enrichment peripherals[] ----------
    # Order matters for determinism: emit by sorted instance name.
    # The SVD's peripheral id sometimes drops the trailing digit
    # (STM32G030 has ``ADC`` not ``ADC1``) so we ALSO emit a
    # digit-stripped alias when the instance name ends in a digit.
    # The merge engine drops phantom rows that don't match a
    # primary peripheral, so the alias is harmless when unused.
    peripherals: list[dict[str, Any]] = []
    emitted_ids: set[str] = set()
    for instance in sorted(set(list(ip_versions) + list(peripheral_pin_options))):
        candidate_ids = [instance]
        stripped = instance.rstrip("0123456789")
        if stripped and stripped != instance:
            candidate_ids.append(stripped)
        for cid in candidate_ids:
            if cid in emitted_ids:
                continue
            emitted_ids.add(cid)
            row: dict[str, Any] = {
                "id":       cid,
                "template": "unknown",   # primary payload's template wins
            }
            if instance in ip_versions:
                row["ip_version"] = ip_versions[instance]
            if instance in peripheral_pin_options:
                row["pin_options"] = {
                    signal: peripheral_pin_options[instance][signal]
                    for signal in sorted(peripheral_pin_options[instance])
                }
            peripherals.append(row)

    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": vendor, "family": family, "device": device,
            "core":   {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
            **({"package": package_raw} if package_raw else {}),
        },
        "provenance": {
            "primary":  f"stm32-open-pin-data:{xml_path.name}",
            "authored": "auto",
        },
        # Schema-required placeholders — merge engine drops these
        # in favour of the primary's authoritative copies.
        "memory": [
            {"id": "flash", "base": "0x00000000", "size": "1B",
             "access": "rx", "role": "extractor-placeholder"},
        ],
        "clock": {
            "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
            "domains":     [{"id": "sysclk", "sources": ["unknown"]}],
        },
        "peripherals": peripherals,
        "pinout":      pinout_rows or [{"signal": "RESET"}],
    }
    return payload


__all__ = ["extract_device"]
