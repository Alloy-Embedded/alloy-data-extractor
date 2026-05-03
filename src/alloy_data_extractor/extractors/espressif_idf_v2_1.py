"""ESP-IDF → v2.1 enrichment extractor.

Reads ESP-IDF source files for ESP32 chips (the upstream
``espressif/esp-idf`` repo's ``components/soc/<chip>/include/soc/``
directory) and emits a v2.1 enrichment payload with two new
classes of data:

* ``hardware_caps`` (root-level extra) — the ``#define SOC_X_Y N``
  table from ``soc_caps.h``.  Captures peripheral counts (UART/
  SPI/I²C/ADC/RMT/...) plus boolean feature flags
  (SOC_DEDICATED_GPIO_SUPPORTED, SOC_RTC_FAST_MEM_SUPPORTED, …).

* ``peripherals[*].gpio_matrix_signals`` — the ``#define
  <SIGNAL>_IDX N`` table from ``gpio_sig_map.h``.  ESP32's GPIO
  matrix is fully runtime-programmable: any peripheral signal can
  route to any GPIO pin by writing the signal index into
  ``GPIO_FUNC<n>_OUT_SEL_CFG_REG`` (output) or
  ``GPIO_FUNC<n>_IN_SEL_CFG_REG`` (input).  This block exposes
  the per-peripheral signal-name → matrix-index map so codegen
  can emit the correct routing register write.

Marked ``provenance.primary = "espressif-idf:components/soc/<chip>"``
so the merge engine routes it through the right priority slot
in ``ESPRESSIF_MERGE_POLICY``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any


# -----------------------------------------------------------------
# soc_caps.h parser
# -----------------------------------------------------------------


_DEFINE_RX = re.compile(
    r"^#define\s+(?P<name>SOC_[A-Z0-9_]+?)\s+(?P<value>[^/\n]+?)(?:\s*//.*)?$",
    re.MULTILINE,
)


def _parse_caps(caps_path: Path) -> dict[str, Any]:
    """Extract every ``#define SOC_X N`` (or boolean ``= 1``)
    from ``soc_caps.h``.

    Skips macro-style defines (function-like with ``(``) since
    those aren't constant values.  Numeric literals and simple
    parenthesised expressions are converted to ``int`` when
    possible; everything else is preserved as the raw string for
    downstream codegen.
    """
    if not caps_path.is_file():
        return {}
    text = caps_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, Any] = {}
    for m in _DEFINE_RX.finditer(text):
        name = m.group("name")
        value = m.group("value").strip()
        # Skip function-like macros (parenthesis right after name).
        # _DEFINE_RX requires whitespace, so this is implicit, but
        # keep a guard for value content.
        if value.startswith("("):
            # Parenthesised expression — try to evaluate when
            # it's a plain integer literal in parens.
            inner = value.strip("()").strip()
            try:
                out[name] = int(inner, 0)
                continue
            except ValueError:
                pass
        try:
            out[name] = int(value, 0)
            continue
        except ValueError:
            pass
        # Boolean
        if value in {"true", "TRUE"}:
            out[name] = True
            continue
        if value in {"false", "FALSE"}:
            out[name] = False
            continue
        # Preserve verbatim for non-numeric values (e.g. cross-refs
        # to other SOC_* macros).
        out[name] = value
    return out


# -----------------------------------------------------------------
# gpio_sig_map.h parser
# -----------------------------------------------------------------


_SIG_DEFINE_RX = re.compile(
    r"^#define\s+(?P<name>[A-Z0-9_]+?)_IDX\s+(?P<value>\d+)\s*$",
    re.MULTILINE,
)

# Direction tag — most signals end in _IN or _OUT; some (like
# SDIO0/CSI) lack the suffix and are bidirectional.
_DIR_RX = re.compile(r"^(?P<base>.*?)_(?P<dir>IN|OUT)$")


def _parse_signals(
    sig_map_path: Path,
    known_peripherals: set[str],
) -> dict[str, dict[str, int]]:
    """Walk ``gpio_sig_map.h`` and bucket signals by peripheral.

    Returns ``{peripheral_lower: {signal_lower: matrix_index}}``.

    Each ``#define <SIGNAL>_IDX <n>`` is split into
    ``(peripheral, signal)`` against ``known_peripherals``
    (longest match wins, like the NXP IOMUXC parser).
    """
    if not sig_map_path.is_file():
        return {}
    text = sig_map_path.read_text(encoding="utf-8", errors="replace")
    bucket: dict[str, dict[str, int]] = defaultdict(dict)
    for m in _SIG_DEFINE_RX.finditer(text):
        name = m.group("name")
        idx = int(m.group("value"))
        # Strip leading underscore on macro guards (e.g.
        # `_SOC_GPIO_SIG_MAP_H_` won't match because it lacks
        # `_IDX`, but defensive).
        if name.startswith("_"):
            continue

        # Strip _IN/_OUT direction suffix when present.
        d_match = _DIR_RX.match(name)
        if d_match:
            base = d_match.group("base")
            direction = d_match.group("dir").lower()
        else:
            base = name
            direction = "bidi"

        # Resolve peripheral by longest match.
        per = _resolve_peripheral(base, known_peripherals)
        if per is None:
            continue
        # Signal = base with peripheral prefix stripped.
        if base.startswith(per + "_"):
            signal_token = base[len(per) + 1:]
        else:
            # Peripheral was a substring inside base (rare).
            signal_token = base

        # Tag direction in signal key.
        signal_key = f"{signal_token}_{direction}".lower()
        # Don't emit duplicate (peripheral, signal) pairs — first
        # win.  The header occasionally redefines aliases.
        bucket[per.lower()].setdefault(signal_key, idx)
    return {p: dict(s) for p, s in bucket.items()}


def _resolve_peripheral(
    base: str, known_peripherals: set[str],
) -> str | None:
    """Find the longest peripheral name in ``known_peripherals``
    that prefixes (or appears as a token in) ``base``."""
    parts = base.split("_")
    n = len(parts)
    best: str | None = None
    best_len = 0
    for end in range(n, 0, -1):
        candidate = "_".join(parts[:end])
        if candidate in known_peripherals and end > best_len:
            best = candidate
            best_len = end
    # Also try common Espressif single-token shortenings.
    # SPI peripherals show up as "SPI", "SPI2", "SPI3"; UARTs
    # as "U0", "U1", "U2".  Normalise to the SVD names.
    if best is None:
        # Map Espressif U<n> shorthand to UART<n>.
        m = re.match(r"^U(\d+)$", base.split("_", 1)[0])
        if m and f"UART{m.group(1)}" in known_peripherals:
            return f"UART{m.group(1)}"
    return best


# -----------------------------------------------------------------
# Per-family device-dir lookup
# -----------------------------------------------------------------


def _device_dir(idf_root: Path, family: str, device: str) -> Path | None:
    """Map (family, device) to ``components/soc/<dir>/`` —
    family-id is usually the directory name (esp32 → esp32,
    esp32c2 → esp32c2, …) but coprocessor devices like
    esp32s2-ulp share their parent's dir."""
    candidates = [family.lower()]
    if device.endswith("-ulp") or device.endswith("-lp"):
        # Coprocessors live alongside the main chip in the IDF tree.
        # The family slug (esp32s2) already points at the right dir.
        pass
    for c in candidates:
        d = idf_root / "components" / "soc" / c
        if d.is_dir():
            return d
    return None


# -----------------------------------------------------------------
# Public entry-point
# -----------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    idf_root: Path,
    known_peripherals: set[str],
) -> dict[str, Any]:
    """Extract ESP-IDF enrichment data for one chip from the
    ``esp-idf/components/soc/<chip>/`` source tree.

    ``known_peripherals`` is the uppercase peripheral-name set
    declared by the chip's CMSIS-SVD primary (used to
    disambiguate signal name → peripheral splits in the
    GPIO matrix table).
    """
    payload: dict[str, Any] = {
        "schema":   "alloy.device.v2.1",
        "identity": {"vendor": vendor, "family": family, "device": device},
        "provenance": {
            "primary":  f"espressif-idf:components/soc/{family}",
            "authored": "auto",
        },
    }

    soc_dir = _device_dir(idf_root, family, device)
    if soc_dir is None:
        return payload

    caps = _parse_caps(soc_dir / "include" / "soc" / "soc_caps.h")
    if caps:
        payload["hardware_caps"] = caps

    if known_peripherals:
        sig_path = soc_dir / "include" / "soc" / "gpio_sig_map.h"
        signals_per_per = _parse_signals(sig_path, known_peripherals)
        if signals_per_per:
            peripherals = []
            for per_id, signals in sorted(signals_per_per.items()):
                peripherals.append({
                    "id": per_id,
                    "gpio_matrix_signals": signals,
                })
            payload["peripherals"] = peripherals

    return payload


__all__ = ["extract_device"]
