"""STM32 tier-2/3/4 → v2.1 enrichment extractor.

Reads STM32_open_pin_data XMLs to discover ``(instance, ip_name,
ip_version)`` triples for the chip, then projects per-IP-version
mapping tables (from :mod:`stm32_tier_mappings`) onto the v2.1
hierarchy:

* ``templates.<ip>.options.<name>`` — lists of semantic option
  values (USART data_bits, SPI baud_prescaler, ADC resolution,
  I²C speed_hz, …).  Encoded values are also surfaced in
  ``templates.<ip>.options.<name>_encoding`` as ``{semantic →
  raw_register_value}`` maps so downstream codegen can produce
  named bit-flips.
* ``templates.<timer>.trigger_sources`` / ``master_outputs`` /
  ``break_inputs`` / ``deadtime_options`` — direct per-IP maps
  for slave-mode triggers, TRGO output mux, advanced-timer
  break inputs, dead-time generator options.
* ``peripherals[<adc>].external_triggers`` — per-instance
  ``{regular: [...], injected: [...]}`` map of EXTSEL field
  values per timer/event source.

Marked ``provenance.primary = "stm32-tier:<chip>"`` so the merge
engine treats it as enrichment.

Covers deltas 4 (ADC external_triggers), 6 (timer trigger_sources),
7 (timer master_outputs), 8 (PWM break_inputs + deadtime_options)
of the v2.1 audit.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractors.stm32_tier_mappings import (
    TierMapping,
    find_tier_mapping,
)


# ---------------------------------------------------------------------------
# Open-pin-data XML helpers (light-weight; doesn't reuse the full
# stm32_open_pin_data_v2_1 to keep tier_v2_1 focused on tier data).
# ---------------------------------------------------------------------------


def _strip_namespace(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.startswith("{"):
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _attr(node: ET.Element, key: str, default: str = "") -> str:
    return node.get(key, default) or default


def _ip_versions(xml_path: Path) -> list[tuple[str, str, str]]:
    """Return list of (instance, ip_name, ip_version) from an
    open-pin-data XML."""
    if not xml_path.is_file():
        return []
    root = _strip_namespace(ET.parse(xml_path))
    out: list[tuple[str, str, str]] = []
    for ip in root.iter("IP"):
        instance = _attr(ip, "InstanceName")
        ip_name = _attr(ip, "Name")
        ip_version = _attr(ip, "Version")
        if instance and ip_name and ip_version:
            out.append((instance, ip_name, ip_version))
    return out


# ---------------------------------------------------------------------------
# v1 projection rows → v2.1 shape converters
# ---------------------------------------------------------------------------


# target_field name (the stm32_tier_mappings convention) → handler
# that turns the per-instance row list into a v2.1 fragment merged
# into the in-progress template / peripheral block.
def _options_list(rows: list[dict[str, Any]], key: str) -> list[Any]:
    """Project rows onto ``[row[key] for row in rows]`` preserving
    declaration order, deduped."""
    out: list[Any] = []
    seen: set[Any] = set()
    for row in rows:
        v = row.get(key)
        if v is None:
            continue
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _encoding_map(rows: list[dict[str, Any]], key: str, value_key: str) -> dict[Any, int]:
    """Project rows onto ``{row[key]: row[value_key]}`` — semantic
    name → raw register value."""
    out: dict[Any, int] = {}
    for row in rows:
        k = row.get(key)
        v = row.get(value_key)
        if k is None or v is None:
            continue
        if k not in out:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Projection dispatcher — one entry per target_field
# ---------------------------------------------------------------------------


# Each handler takes (rows_for_this_instance, instance, target_template,
# target_peripheral, accumulator).  Mutates the accumulator dict in
# place.  Accumulator shape:
#
#   accumulator["templates"][<ip>]    — template fragments
#   accumulator["peripherals"][<id>]  — per-instance fragments
ProjectionHandler = Callable[
    [list[dict[str, Any]], str, str, str, dict[str, Any]],
    None,
]


def _instance_id(instance: str) -> str:
    return instance.lower()


# ---- USART / UART ---------------------------------------------------------


def _h_uart_data_bits(rows, instance, template, _peripheral_id, acc):
    bits = _options_list(rows, "bits")
    if not bits:
        return
    enc: dict[str, int] = {}
    for r in rows:
        if "bits" not in r:
            continue
        # m0_value+m1_value combine into a 2-bit encoding:
        # USART CR1.M = m0 << 12 + m1 << 28 (template-specific in
        # codegen).  We stash them under a unified ``data_bits_encoding``.
        m0 = r.get("m0_value")
        m1 = r.get("m1_value")
        if m0 is None and m1 is None:
            continue
        enc[f"{r['bits']}bit"] = (int(m1 or 0) << 1) | int(m0 or 0)
    template_block = acc["templates"].setdefault(template, {})
    options = template_block.setdefault("options", {})
    options.setdefault("data_bits", bits)
    if enc:
        options.setdefault("data_bits_encoding", enc)


def _h_uart_parity(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    parity_list = _options_list(rows, "parity")
    if parity_list:
        options.setdefault("parity", parity_list)
        enc = _encoding_map(rows, "parity", "field_value")
        if enc:
            options.setdefault("parity_encoding", {str(k): v for k, v in enc.items()})


def _h_uart_stop_bits(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    stop_list = _options_list(rows, "stop_bits")
    if stop_list:
        options.setdefault("stop_bits", [str(s) for s in stop_list])
        enc = _encoding_map(rows, "stop_bits", "field_value")
        if enc:
            options.setdefault("stop_bits_encoding", {str(k): v for k, v in enc.items()})


def _h_uart_mode_flags(rows, instance, template, _peripheral_id, acc):
    flags = _options_list(rows, "flag")
    if flags:
        acc["templates"].setdefault(template, {}).setdefault(
            "options", {}).setdefault("mode_flags", flags)


# ---- SPI ------------------------------------------------------------------


def _h_spi_baud_prescaler(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    prescalers = _options_list(rows, "divisor")
    if prescalers:
        options.setdefault("baud_prescaler", [f"div_{p}" for p in prescalers])
        enc = {f"div_{r['divisor']}": r["field_value"]
               for r in rows if r.get("divisor") is not None and r.get("field_value") is not None}
        if enc:
            options.setdefault("baud_prescaler_encoding", enc)


def _h_spi_mode_flags(rows, instance, template, _peripheral_id, acc):
    flags = _options_list(rows, "flag")
    if flags:
        acc["templates"].setdefault(template, {}).setdefault(
            "options", {}).setdefault("mode_flags", flags)


# ---- I²C -----------------------------------------------------------------


def _h_i2c_speed_options(rows, instance, template, _peripheral_id, acc):
    speeds = _options_list(rows, "speed_hz")
    if speeds:
        from alloy_data_extractor.extractors.stm32_overlay_v2_1 import _hz_with_unit
        speeds_str = [_hz_with_unit(s) for s in speeds]
        acc["templates"].setdefault(template, {}).setdefault(
            "options", {}).setdefault("speeds", speeds_str)


def _h_i2c_mode_flags(rows, instance, template, _peripheral_id, acc):
    flags = _options_list(rows, "flag")
    if flags:
        acc["templates"].setdefault(template, {}).setdefault(
            "options", {}).setdefault("mode_flags", flags)


# ---- ADC ------------------------------------------------------------------


def _h_adc_resolution(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    res_list = _options_list(rows, "bits")
    if res_list:
        options.setdefault("resolution", res_list)
        enc = _encoding_map(rows, "bits", "field_value")
        if enc:
            options.setdefault("resolution_encoding",
                               {f"{k}bit": v for k, v in enc.items()})


def _h_adc_sample_time(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    cycles = _options_list(rows, "cycles")
    if cycles:
        options.setdefault("sample_time_cycles", cycles)
        enc = _encoding_map(rows, "cycles", "field_value")
        if enc:
            options.setdefault("sample_time_encoding",
                               {str(k): v for k, v in enc.items()})


def _h_adc_oversampling(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    ratios = _options_list(rows, "ratio")
    if ratios:
        options.setdefault("oversampling", ratios)


def _h_adc_external_triggers(rows, instance, _template, peripheral_id, acc):
    """Per-instance — populates peripherals[<adc>].external_triggers."""
    if not rows:
        return
    regular_rows: list[dict[str, Any]] = []
    for r in rows:
        source = r.get("source")
        extsel = r.get("extsel_value")
        if source is None or extsel is None:
            continue
        entry: dict[str, Any] = {"source": source, "extsel": extsel}
        polarity = r.get("default_polarity")
        if polarity is not None:
            # v1 used 0/1/2 ints; v2.1 wants names.
            entry["polarity"] = {1: "rising", 2: "falling", 3: "both"}.get(
                int(polarity), "rising",
            )
        regular_rows.append(entry)
    if not regular_rows:
        return
    per_block = acc["peripherals"].setdefault(
        peripheral_id, {"id": peripheral_id, "template": "adc"},
    )
    triggers = per_block.setdefault("external_triggers", {})
    triggers["regular"] = regular_rows


# ---- Timers + PWM ---------------------------------------------------------


def _h_timer_prescaler(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    presc = _options_list(rows, "value")
    if presc:
        options.setdefault("prescaler", presc)


def _h_timer_trigger_sources(rows, instance, template, _peripheral_id, acc):
    enc = _encoding_map(rows, "source", "field_value")
    if enc:
        acc["templates"].setdefault(template, {}).setdefault(
            "trigger_sources", {str(k): v for k, v in enc.items()})


def _h_timer_master_outputs(rows, instance, template, _peripheral_id, acc):
    enc = _encoding_map(rows, "source", "field_value")
    if enc:
        acc["templates"].setdefault(template, {}).setdefault(
            "master_outputs", {str(k): v for k, v in enc.items()})


def _h_timer_mode_flags(rows, instance, template, _peripheral_id, acc):
    flags = _options_list(rows, "flag")
    if flags:
        acc["templates"].setdefault(template, {}).setdefault(
            "capabilities_extra", flags)


def _h_pwm_alignment_options(rows, instance, template, _peripheral_id, acc):
    options = acc["templates"].setdefault(template, {}).setdefault("options", {})
    aligns = _options_list(rows, "alignment")
    if aligns:
        options.setdefault("alignment", aligns)


def _h_pwm_break_inputs(rows, instance, template, _peripheral_id, acc):
    inputs = _options_list(rows, "input_id")
    if inputs:
        acc["templates"].setdefault(template, {}).setdefault(
            "break_inputs", inputs)


def _h_pwm_deadtime_options(rows, instance, template, _peripheral_id, acc):
    if not rows:
        return
    out_rows: list[dict[str, Any]] = []
    for r in rows:
        # Translate v1 row keys to v2.1 deadtime_option shape.
        out: dict[str, Any] = {}
        if "prescaler_field_value" in r:
            out["dtg_prescaler"] = r["prescaler_field_value"]
        if "count_bits" in r:
            out["count_bits"] = r["count_bits"]
        if "max_ns" in r:
            out["max_ns"] = r["max_ns"]
        if out:
            out_rows.append(out)
    if out_rows:
        acc["templates"].setdefault(template, {}).setdefault(
            "deadtime_options", out_rows)


def _h_pwm_mode_flags(rows, instance, template, _peripheral_id, acc):
    flags = _options_list(rows, "flag")
    if flags:
        acc["templates"].setdefault(template, {}).setdefault(
            "capabilities_extra", flags)


# Dispatch table
_HANDLERS: dict[str, ProjectionHandler] = {
    "uart_data_bits_options":    _h_uart_data_bits,
    "uart_parity_options":       _h_uart_parity,
    "uart_stop_bits_options":    _h_uart_stop_bits,
    "uart_mode_flags":           _h_uart_mode_flags,
    "spi_baud_prescaler_options": _h_spi_baud_prescaler,
    "spi_mode_flags":            _h_spi_mode_flags,
    "i2c_speed_options":         _h_i2c_speed_options,
    "i2c_mode_flags":            _h_i2c_mode_flags,
    "adc_resolution_options":    _h_adc_resolution,
    "adc_sample_time_options":   _h_adc_sample_time,
    "adc_oversampling_options":  _h_adc_oversampling,
    "adc_external_triggers":     _h_adc_external_triggers,
    "timer_prescaler_options":   _h_timer_prescaler,
    "timer_trigger_sources":     _h_timer_trigger_sources,
    "timer_master_outputs":      _h_timer_master_outputs,
    "timer_mode_flags":          _h_timer_mode_flags,
    "pwm_alignment_options":     _h_pwm_alignment_options,
    "pwm_break_inputs":          _h_pwm_break_inputs,
    "pwm_deadtime_options":      _h_pwm_deadtime_options,
    "pwm_mode_flags":            _h_pwm_mode_flags,
}


# ---------------------------------------------------------------------------
# IP class → v2.1 template id resolution.  STM32 IP names map to
# template ids in the canonical YAML; the convention is lowercased
# IP name with vendor-specific aliases (TIM1_8G0 → timer_advanced,
# gptimer1_v2_x → timer_general, etc.).
# ---------------------------------------------------------------------------


def _resolve_template_id(ip_name: str) -> str:
    n = ip_name.lower()
    # Timer family — distinguish advanced vs general where possible.
    if "tim1_8" in n:
        return "timer_advanced"
    if "tim" in n and "gptimer" in n:
        return "timer_general"
    if n == "gpio":
        return "gpio"
    if n == "usart":
        return "usart"
    if n == "uart":
        return "uart"
    if n == "spi":
        return "spi"
    if n == "i2c":
        return "i2c"
    if n == "adc":
        return "adc"
    return n


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    open_pin_data_xml: Path,
) -> dict[str, Any]:
    """Project tier-2/3/4 mappings onto the v2.1 enrichment shape.

    Reads the open-pin-data XML for the chip to discover
    ``(instance, ip_name, ip_version)`` triples; for each triple
    looks up the matching :class:`TierMapping` and runs every
    projection through the v2.1 handler dispatch table.
    """
    triples = _ip_versions(open_pin_data_xml)
    accumulator: dict[str, dict[str, Any]] = {
        "templates":   defaultdict(dict),
        "peripherals": {},
    }

    for instance, ip_name, ip_version in triples:
        mapping: TierMapping | None = find_tier_mapping(ip_name, ip_version)
        if mapping is None:
            continue
        template_id = _resolve_template_id(ip_name)
        instance_id = _instance_id(instance)
        # Emit per-instance fragments under BOTH the digit-suffixed
        # id (matching CubeMX/open-pin-data convention) and the
        # digit-stripped alias (matching the SVD's spelling on
        # smaller chips, e.g. STM32G030 declares ``ADC`` not
        # ``ADC1``).  The merge engine drops phantom rows that don't
        # match a primary peripheral.
        instance_id_aliases = {instance_id}
        stripped = instance_id.rstrip("0123456789")
        if stripped and stripped != instance_id:
            instance_id_aliases.add(stripped)
        for projection in mapping.projections:
            handler = _HANDLERS.get(projection.target_field)
            if handler is None:
                continue
            rows = projection.project(instance)
            for inst_alias in instance_id_aliases:
                handler(rows, instance, template_id, inst_alias, accumulator)

    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {
            "vendor": vendor, "family": family, "device": device,
            "core":   {"isa": "armv6-m", "name": "cortex-m0plus", "bits": 32},
        },
        "provenance": {
            "primary":  f"stm32-tier:{device}",
            "authored": "auto",
            "notes":    "Tier-2/3/4 projection from per-IP-version mapping tables.",
        },
        "memory": [
            {"id": "flash", "base": "0x00000000", "size": "1B",
             "access": "rx", "role": "extractor-placeholder"},
        ],
        "clock": {
            "oscillators": {"unknown": {"freq": "0Hz", "kind": "rc-internal"}},
            "domains":     [{"id": "sysclk", "sources": ["unknown"]}],
        },
    }

    templates = {ip: dict(t) for ip, t in accumulator["templates"].items() if t}
    if templates:
        payload["templates"] = templates

    peripherals = list(accumulator["peripherals"].values())
    payload["peripherals"] = peripherals
    payload["pinout"] = [{"signal": "RESET"}]
    return payload


__all__ = ["extract_device"]
