"""Auto-generate a v2.1 ``family.toml`` overlay from one ATDF.

Reads the chip's ``<property-group name="ELECTRICAL_CHARACTERISTICS">``
for ``CHIP_FREQ_CPU_MAX`` and the largest variant's
``<memory-segment>`` table, then writes the canonical layout
that matches the hand-curated SAME70/SAMD21/SAMD51/etc overlays.

Per the user mandate "nada feito na mão" — instead of writing
20+ overlays by hand for SAMC20/C21/D09/D10/D11/D20/DA1/E51/E53/
E54/G/HA0/HA1/L10/L11/L22/R21/R30/R34/R35/RH707/RH71/S70/V70,
this script derives them from the ATDF itself.  The values are
conservative (max clocks default to CPU_MAX, peripheral max
clocks to half of CPU_MAX, I²C to fast-mode-plus 1 MHz which
every modern Atmel SERCOM/TWIHS supports) and can be refined
per-family with hand-tuned values when needed.

Usage::

    python3 scripts/scaffold_family_overlay.py \\
        --family samg \\
        --atdf <microchip-dfp>/samg-*/samg55/atdf/ATSAMG55J19.atdf \\
        --out data/vendors/microchip/samg/family.toml
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


_ATDF_TYPE_TO_KIND = {
    "flash":  "flash",
    "ram":    "sram",
    "io":     "io",
    "rom":    "rom",
    "other":  "external",
    "eeprom": "eeprom",
}

# Memory-segment name → optional v2.1 "role" tag.  Mirrors what
# the hand-curated overlays use so the scaffolded output is
# indistinguishable.
_NAME_TO_ROLE = {
    "ITCM":   "tcm",
    "DTCM":   "tcm",
    "IROM":   "boot-rom",
    "BOOTROM": "boot-rom",
    "BOOT":   "boot-rom",
    "QSPIMEM": "xip",
    "QSPI":   "xip",
    "EBI_CS0": "external-bus",
    "EBI_CS1": "external-bus",
    "EBI_CS2": "external-bus",
    "EBI_CS3": "external-bus",
    "BACKUP_SRAM": "battery-backed",
    "BKUPRAM":     "battery-backed",
    "LPRAM":       "low-power-retention",
    "RWWFLASH":    "rww-eeprom-emul",
}


def _parse_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(s, 0)
    except ValueError:
        return None


def _format_size(size: int) -> str:
    """Render a TOML literal for ``size_bytes`` — keep raw int but
    annotate the unit in a comment for readability."""
    if size >= (1 << 30) and size % (1 << 30) == 0:
        return f"{size}  # {size >> 30} GB"
    if size >= (1 << 20) and size % (1 << 20) == 0:
        return f"{size}  # {size >> 20} MB"
    if size >= 1024 and size % 1024 == 0:
        return f"{size}  # {size // 1024} KB"
    return f"{size}"


def _format_freq_hz(hz: int) -> str:
    """4_000_000 ⇒ '4_000_000  # 4 MHz'."""
    underscore = f"{hz:_}"
    if hz >= 1_000_000 and hz % 1_000_000 == 0:
        return f"{underscore}  # {hz // 1_000_000} MHz"
    if hz >= 1_000 and hz % 1_000 == 0:
        return f"{underscore}  # {hz // 1_000} kHz"
    return f"{underscore}  # {hz} Hz"


def _walk_memory(root: ET.Element) -> list[dict]:
    out = []
    seen_keys: set[tuple[str, int]] = set()
    for aspace in root.iter("address-space"):
        for seg in aspace.iter("memory-segment"):
            name = seg.get("name", "")
            base = _parse_int(seg.get("start", ""))
            size = _parse_int(seg.get("size", ""))
            seg_type = seg.get("type", "").lower()
            rw = seg.get("rw", "").upper()
            exec_flag = seg.get("exec", "") in {"1", "true"}
            if not name or base is None or size is None:
                continue
            key = (name, base)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            kind = _ATDF_TYPE_TO_KIND.get(seg_type, "external")
            access = (
                "rwx" if "W" in rw and exec_flag
                else "rw" if "W" in rw
                else "rx" if exec_flag or "X" in rw
                else "ro"
            )
            row = {
                "name": name,
                "kind": kind,
                "base_address": base,
                "size_bytes":   size,
                "access":       access,
            }
            role = _NAME_TO_ROLE.get(name)
            if role:
                row["role"] = role
            elif kind == "flash":
                row["address_space"] = "code"
            elif kind == "sram" and base >= 0x2000_0000 and size >= 16384:
                row["address_space"] = "data"
            out.append(row)
    return out


def _detect_cpu_max(root: ET.Element) -> int | None:
    for prop in root.iter("property"):
        if prop.get("name") == "CHIP_FREQ_CPU_MAX":
            return _parse_int(prop.get("value", ""))
    return None


def _detect_core_label(root: ET.Element) -> str:
    dev = root.find(".//device")
    if dev is None:
        return "Cortex-M"
    arch = (dev.get("architecture") or "").upper()
    if "M0PLUS" in arch:
        return "Cortex-M0+"
    if "M0" in arch:
        return "Cortex-M0"
    if "M3" in arch:
        return "Cortex-M3"
    if "M4" in arch:
        return "Cortex-M4F"
    if "M7" in arch:
        return "Cortex-M7F"
    return arch.title()


def render_family_toml(family: str, atdf_path: Path) -> str:
    root = ET.parse(atdf_path).getroot()
    cpu_max = _detect_cpu_max(root) or 48_000_000
    core_label = _detect_core_label(root)
    memory = _walk_memory(root)

    # Conservative ADC / UART / SPI ceilings derived from CPU_MAX.
    # Real datasheet values are usually CPU/2..CPU/4 — close enough
    # for codegen sanity bounds; family overlays can tighten.
    adc_max = min(cpu_max // 2, 16_000_000)
    uart_max = cpu_max // 8 if cpu_max > 0 else 3_000_000
    spi_max = cpu_max // 2 if cpu_max > 0 else 12_000_000

    lines: list[str] = []
    lines.append(f"# {family.upper()} family overlay — auto-scaffolded by")
    lines.append(f"# scripts/scaffold_family_overlay.py from {atdf_path.name}.")
    lines.append(f"#")
    lines.append(f"# Core (per ATDF <device architecture>): {core_label}")
    lines.append(f"# CHIP_FREQ_CPU_MAX:                     {cpu_max:_} Hz")
    lines.append(f"#")
    lines.append("# Refine peripheral max clocks from the family datasheet")
    lines.append("# when you need silicon-accurate ceilings — these are")
    lines.append("# conservative defaults derived from CPU_MAX.")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# ADC / UART / SPI / I²C max clocks")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")
    lines.append("[adc]")
    lines.append(f"max_clock_hz = {_format_freq_hz(adc_max)}")
    lines.append("")
    lines.append("[uart]")
    lines.append(f"max_baud_hz = {_format_freq_hz(uart_max)}")
    lines.append("")
    lines.append("[spi]")
    lines.append(f"max_clock_hz = {_format_freq_hz(spi_max)}")
    lines.append("")
    lines.append("[i2c]")
    lines.append("max_clock_hz = 1_000_000  # 1 MHz (Fast-Mode-Plus, "
                 "supported by every modern Atmel SERCOM/TWIHS)")
    lines.append("")
    for n, hz in (("standard", 100_000), ("fast", 400_000), ("fast_plus", 1_000_000)):
        lines.append("[[i2c.speed_options]]")
        lines.append(f'name = "{n}"')
        lines.append(f"speed_hz = {hz:_}")
        lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Memory regions (auto-populated from ATDF <address-space><memory-segment>)")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")
    for row in memory:
        lines.append("[[memories]]")
        lines.append(f'name = "{row["name"]}"')
        lines.append(f'kind = "{row["kind"]}"')
        lines.append(f"base_address = 0x{row['base_address']:08X}")
        lines.append(f"size_bytes = {_format_size(row['size_bytes'])}")
        lines.append(f'access = "{row["access"]}"')
        if "role" in row:
            lines.append(f'role = "{row["role"]}"')
        if "address_space" in row:
            lines.append(f'address_space = "{row["address_space"]}"')
        lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# System clock — minimal post-reset + max profile.")
    lines.append("# Refine with PLL params + named oscillators per family datasheet.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")
    lines.append("[system_clock.post_reset_profile]")
    lines.append('name = "factory-default"')
    # Default post-reset CPU clock — 1 MHz for M0+, 4 MHz for M4F+,
    # 12 MHz for M7F (matches what SAME70 ATDF sets for MAINCK_RC).
    if "M7" in core_label:
        post_reset_hz = 4_000_000
    elif "M4" in core_label:
        post_reset_hz = 4_000_000
    else:
        post_reset_hz = 1_000_000
    lines.append(f"sysclk_hz = {_format_freq_hz(post_reset_hz)}")
    lines.append(f"hclk_hz = {_format_freq_hz(post_reset_hz)}")
    lines.append(f"pclk_hz = {_format_freq_hz(post_reset_hz)}")
    lines.append('source = "internal-rc"')
    lines.append("")
    lines.append("[[system_clock.recommended_profiles]]")
    lines.append(f'name = "{core_label.lower().replace("+", "plus").replace("-", "")}-max"')
    lines.append(f"sysclk_hz = {_format_freq_hz(cpu_max)}")
    lines.append(f"hclk_hz = {_format_freq_hz(cpu_max)}")
    pclk_hz = cpu_max // 2 if cpu_max > 100_000_000 else cpu_max
    lines.append(f"pclk_hz = {_format_freq_hz(pclk_hz)}")
    lines.append('source = "pll"')
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True,
                        help="Family slug (samg, samc21, …)")
    parser.add_argument("--atdf", type=Path, required=True,
                        help="Path to a representative ATDF for this family")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output family.toml path")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing overlay")
    args = parser.parse_args(argv)

    if args.out.exists() and not args.force:
        print(f"  ! {args.family}: {args.out} already exists "
              "(use --force to overwrite)", file=sys.stderr)
        return 0

    if not args.atdf.is_file():
        print(f"  ✗ {args.family}: ATDF not found at {args.atdf}",
              file=sys.stderr)
        return 1

    text = render_family_toml(args.family, args.atdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    n_mem = text.count("[[memories]]")
    cpu = "?" if "CHIP_FREQ_CPU_MAX:" not in text else \
          text.split("CHIP_FREQ_CPU_MAX:")[1].split("\n")[0].strip()
    print(f"  ✓ {args.family}: scaffolded {args.out} "
          f"({n_mem} memory rows, CPU max {cpu})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
