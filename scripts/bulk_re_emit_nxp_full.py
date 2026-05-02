"""Bulk-emit every NXP / legacy-Freescale chip with the
``cmsis_svd_v2_1`` extractor.

Discovery walks ``<svd_root>/{NXP,Freescale}/*.svd`` from the
upstream `cmsis-svd-data` repo (sparse-checkout for
``data/NXP`` + ``data/Freescale``) and routes every SVD through
the existing extractor used for STMicro.  CMSIS-SVD is
self-contained — no separate IRQ table or pinout source needed.

Family slug derivation:

  * LPC<dd>...           → ``lpc<dd>``     (lpc11, lpc15, lpc54)
  * LPC8...              → ``lpc8``        (LPC800/LPC802 line)
  * MIMXRT*              → ``mimxrt``      (i.MX RT1010..RT1064)
  * MK<dd><letter>*      → ``mk<dd><l>``   (mk22f, mk64f, mk82f)
  * MKE<dd>*             → ``mke<dd>``     (Kinetis E series)
  * MKL<dd>*             → ``mkl<dd>``     (Kinetis L low-power)
  * MKM<dd>*             → ``mkm<dd>``     (metering)
  * MKS<dd><letter>*     → ``mks<dd><l>``  (energy meter)
  * MKV<dd><letter>*     → ``mkv<dd><l>``  (motor control)
  * MKW<dd><letter>*     → ``mkw<dd><l>``  (wireless)
  * QN<digits>*          → ``qn``          (QN908x BLE)
  * SKEA*                → ``skea``        (Kinetis EA)

Per-chip device id = SVD basename, lowercased (versioning
suffixes like ``_v6a``, ``_svd_v1`` get stripped).

Usage::

    python3 scripts/bulk_re_emit_nxp_full.py \\
        --svd-root <cache>/cmsis-svd-data/data \\
        --out      /path/to/alloy-devices-yml
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_CODEGEN_SRC = ROOT.parent / "alloy-codegen" / "src"
if _CODEGEN_SRC.is_dir() and str(_CODEGEN_SRC) not in sys.path:
    sys.path.insert(0, str(_CODEGEN_SRC))

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml  # noqa: E402
from alloy_data_extractor.extractors.cmsis_svd_v2_1 import (  # noqa: E402
    extract_device as svd_extract,
)


# Regex that strips trailing version / suffix decoration so the
# device-id slug stays clean.  Examples:
#   "LPC11Cxx_v9"        → "lpc11cxx"
#   "LPC176x5x_v0.2"     → "lpc176x5x"
#   "LPC11D14_svd_v4"    → "lpc11d14"
#   "LPC11Axxv0.6"       → "lpc11axx"  (no underscore!)
_SUFFIX_RX = re.compile(
    r"(_(?:svd_)?v\d+(\.\d+)?[a-z]?|v\d+(\.\d+)?[a-z]?)$",
    re.IGNORECASE,
)


def _device_id(svd_stem: str) -> str:
    cleaned = _SUFFIX_RX.sub("", svd_stem)
    return cleaned.lower()


def _family_slug(device_id: str) -> str:
    """Derive a v2.1 family slug from the lowercased device id."""
    s = device_id

    if s.startswith("mimxrt"):
        return "mimxrt"
    if s.startswith("qn"):
        return "qn"
    if s.startswith("skea"):
        return "skea"

    # LPC families — group by 2-digit prefix when present, else
    # fall back to the LPC8xx single-bucket.
    m = re.match(r"^lpc(\d{2,3})", s)
    if m:
        digits = m.group(1)
        if digits.startswith("8") and len(digits) == 3:
            return "lpc8"
        return f"lpc{digits[:2]}"

    # MK family with X letter — mk<dd><letter>.  Drop trailing
    # qualifier letters/numbers (MK10D5 → mk10d, MK64F12 → mk64f,
    # MK22F25612 → mk22f, MK21FA12 → mk21fa).
    m = re.match(r"^mk(\d+)([a-z]+)", s)
    if m:
        digits = m.group(1)
        letter = m.group(2)
        # Letter chunk is usually 1-2 chars (D, F, FA, DA, DZ); cap at 2.
        return f"mk{digits}{letter[:2]}"

    # Catch-all — return the device id as-is so the run doesn't
    # silently lose chips.
    return s


def _re_emit_one(
    *,
    svd_path: Path,
    output_root: Path,
) -> tuple[Path, str]:
    device = _device_id(svd_path.stem)
    family = _family_slug(device)
    payload = svd_extract(
        vendor="nxp", family=family, device=device, svd_path=svd_path,
    )
    out_path = write_device_yaml(
        payload=payload, output_root=output_root,
        vendor="nxp", family=family, device=device,
    )
    return out_path, family


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svd-root", type=Path, required=True,
                        help="Root containing NXP/ and Freescale/ subdirs "
                             "(usually <cache>/cmsis-svd-data/data)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--families", default="",
                        help="Comma-separated subset (default = every family)")
    args = parser.parse_args(argv)

    svds: list[Path] = []
    for sub in ("NXP", "Freescale"):
        sub_dir = args.svd_root / sub
        if not sub_dir.is_dir():
            print(f"  ! {sub_dir} not present, skipping")
            continue
        svds.extend(sorted(sub_dir.glob("*.svd")))

    if not svds:
        print(f"ERROR: no SVDs found under {args.svd_root}",
              file=sys.stderr)
        return 1

    if args.families:
        wanted = {f.strip() for f in args.families.split(",") if f.strip()}
        svds = [s for s in svds
                if _family_slug(_device_id(s.stem)) in wanted]

    print(f"Re-emitting {len(svds)} chip(s) into {args.out}")
    print()

    failures = 0
    by_family: dict[str, list[tuple[Path, bool, str]]] = defaultdict(list)
    for svd in svds:
        try:
            out_path, fam = _re_emit_one(
                svd_path=svd, output_root=args.out,
            )
            by_family[fam].append((out_path, True, ""))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fam = _family_slug(_device_id(svd.stem))
            by_family[fam].append((svd, False, f"{type(exc).__name__}: {exc}"))

    grand_ok = 0
    grand_fail = 0
    for fam in sorted(by_family):
        rows = by_family[fam]
        ok = sum(1 for r in rows if r[1])
        fail = len(rows) - ok
        grand_ok += ok
        grand_fail += fail
        status = "✓" if fail == 0 else "⚠"
        print(f"  {status} {fam:10s} {ok:>3}/{len(rows):<3} chips")
        for path, success, msg in rows:
            if not success:
                print(f"      ✗ {path.stem}: {msg[:80]}")

    print()
    print(f"TOTAL: {grand_ok} ok, {grand_fail} failed across "
          f"{len(by_family)} family(ies)")
    return 1 if grand_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
