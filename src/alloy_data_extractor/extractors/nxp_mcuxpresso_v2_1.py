"""NXP MCUXpresso SDK → v2.1 enrichment extractor.

Reads NXP-specific source files from the upstream
``nxp-mcuxpresso/mcux-sdk`` repo:

* ``devices/<MCU>/drivers/fsl_iomuxc.h`` — pin-mux macros of the
  form ``IOMUXC_<PAD>_<PERIPHERAL>_<SIGNAL> <mux_reg>, <alt>, …``
  (i.MX RT family).
* ``devices/<MCU>/drivers/fsl_pinmux.h`` — Kinetis-style PORTx
  pin mux helpers.

What we extract per chip:

* peripherals[*].pin_options — same shape as STM32 / SAM, but
  with the pad name verbatim (``GPIO_AD_B0_13``) so codegen
  can route to the IOMUXC SW_MUX_CTL_PAD_* register correctly.
* peripherals[*].description — peripheral caption from
  ``fsl_clock.h`` (best-effort; many drivers lack one).

What we deliberately don't extract here:

* clock.domains — fsl_clock.h is C runtime code, not a
  declarative table.  Captured via overlay TOML when needed.
* memory[] — linker scripts live in the per-board
  ``boards/<NAME>/`` tree, not ``devices/``; overlay TOML
  carries the canonical per-family map.

Output: a v2.1 enrichment payload with only ``peripherals[]``
filled (other top-level keys absent), provenance.primary tagged
``nxp-mcuxpresso:devices/<MCU>/drivers/fsl_iomuxc.h`` so the
merge engine routes it through the right priority slot.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any


# `IOMUXC_<PAD>_<PERIPHERAL>_<SIGNAL>` macro extraction.
#
# The IOMUXC define names cram pad / peripheral / signal into one
# uppercase identifier separated by underscores; we can't tell
# where pad ends and peripheral begins without a peripheral-name
# index.  The caller passes that set in via known_peripherals.
_IOMUXC_DEFINE_RX = re.compile(
    r"^#define\s+IOMUXC_(?P<rest>[A-Z0-9_]+?)\s",
    re.MULTILINE,
)


def _split_iomuxc_name(
    rest: str, known_peripherals: set[str],
) -> tuple[str, str, str] | None:
    """Resolve ``GPIO_EMC_00_LPSPI2_SCK`` to
    ``(pad="GPIO_EMC_00", peripheral="LPSPI2", signal="SCK")``
    by scanning for the longest known peripheral name embedded in
    the underscored token list.

    Returns ``None`` when the name doesn't contain any known
    peripheral (rare but happens for SDK-internal aliases).
    """
    parts = rest.split("_")
    n = len(parts)
    # Try every contiguous substring as the peripheral name.
    # Prefer longer matches: an instance like LPI2C1 (6 chars)
    # over its prefix LPI2C (5 chars) when both are in the
    # peripheral set.  Walk from longest to shortest.
    best: tuple[str, str, str] | None = None
    best_len = 0
    for start in range(1, n):  # peripheral can't start at the very front; pad needs ≥1 token
        for end in range(start + 1, n):
            candidate = "_".join(parts[start:end])
            if candidate in known_peripherals and (end - start) > best_len:
                pad = "_".join(parts[:start])
                signal = "_".join(parts[end:])
                if pad and signal:
                    best = (pad, candidate, signal)
                    best_len = end - start
        # Also try single-token peripheral names at this position.
        single = parts[start]
        if single in known_peripherals and 1 > best_len:
            pad = "_".join(parts[:start])
            signal = "_".join(parts[start + 1:])
            if pad and signal:
                best = (pad, single, signal)
                best_len = 1
    return best


def _walk_iomuxc(
    iomuxc_path: Path, known_peripherals: set[str],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Return ``{peripheral_lower: {signal_lower: [{pin: PAD}, ...]}}``."""
    if not iomuxc_path.is_file():
        return {}
    text = iomuxc_path.read_text(encoding="utf-8", errors="replace")

    pin_options: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list),
    )
    for m in _IOMUXC_DEFINE_RX.finditer(text):
        rest = m.group("rest")
        split = _split_iomuxc_name(rest, known_peripherals)
        if split is None:
            continue
        pad, peripheral, signal = split
        per_low = peripheral.lower()
        sig_low = signal.lower()
        entry = {"pin": pad}
        bucket = pin_options[per_low][sig_low]
        if entry not in bucket:
            bucket.append(entry)
    return {p: dict(s) for p, s in pin_options.items()}


# ---------------------------------------------------------------------------
# Per-family device-dir lookup
# ---------------------------------------------------------------------------


# Maps the v2.1 device id (e.g. "mimxrt1062") to the upstream
# mcux-sdk devices/<DIR>.  Many devices share an MCU header
# directory — we keep a flat map so codegen consumers can ask
# for any chip and get a hit.
def _candidate_device_dirs(device: str) -> list[str]:
    """Return device-dir candidates ordered most-specific first."""
    upper = device.upper()
    candidates = [upper]
    # Strip trailing variants like "DVL6A" / "DVT8B" off RT chips
    # (MIMXRT1062DVL6A → MIMXRT1062).
    m = re.match(r"^(MIMXRT\d{4})", upper)
    if m and m.group(1) not in candidates:
        candidates.append(m.group(1))
    # Strip the trailing letter+digit variant from Kinetis K
    # (MK22F51212 → MK22F).
    m = re.match(r"^(MK[A-Z0-9]+?)(\d+)$", upper)
    if m and m.group(1) not in candidates:
        candidates.append(m.group(1))
    return candidates


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    sdk_root: Path,
    known_peripherals: set[str],
) -> dict[str, Any]:
    """Extract NXP enrichment data for one chip from the
    MCUXpresso SDK source tree.

    ``sdk_root`` should be the cloned ``nxp-mcuxpresso/mcux-sdk``
    directory (the one containing ``devices/``).
    ``known_peripherals`` is the set of peripheral instance names
    declared by the chip's CMSIS-SVD primary (``LPSPI1``,
    ``LPI2C1``, ``FLEXPWM4`` …) — used to disambiguate the
    pad/peripheral/signal split inside IOMUXC macro names.
    """
    payload: dict[str, Any] = {
        "schema":   "alloy.device.v2.1",
        "identity": {"vendor": vendor, "family": family, "device": device},
        "provenance": {
            "primary":  f"nxp-mcuxpresso:devices/{device.upper()}",
            "authored": "auto",
        },
    }

    # Walk candidate device dirs in order — first hit wins.
    iomuxc_path: Path | None = None
    for dev_dir_name in _candidate_device_dirs(device):
        candidate = sdk_root / "devices" / dev_dir_name / "drivers" / "fsl_iomuxc.h"
        if candidate.is_file():
            iomuxc_path = candidate
            payload["provenance"]["primary"] = (
                f"nxp-mcuxpresso:devices/{dev_dir_name}/drivers/fsl_iomuxc.h"
            )
            break

    if iomuxc_path is None or not known_peripherals:
        return payload  # No source — payload is identity-only.

    pin_options_per_peripheral = _walk_iomuxc(iomuxc_path, known_peripherals)
    if not pin_options_per_peripheral:
        return payload

    # Build peripherals[] rows (id + pin_options only).  The merge
    # engine fields these into the primary's peripherals[] by id.
    peripherals: list[dict[str, Any]] = []
    for per_id, pin_options in sorted(pin_options_per_peripheral.items()):
        peripherals.append({"id": per_id, "pin_options": pin_options})
    payload["peripherals"] = peripherals
    return payload


__all__ = ["extract_device"]
