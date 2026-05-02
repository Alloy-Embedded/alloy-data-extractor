"""Bulk-emit every Renesas chip with the ``cmsis_svd_v2_1`` extractor.

Discovery walks ``<svd_root>/Renesas/*.svd`` from the upstream
``cmsis-svd-data`` repo (sparse-checkout for ``data/Renesas``)
and routes every SVD through the existing CMSIS-SVD extractor
used for STM and NXP.

Family-slug derivation (Renesas RA series):
  * R7FA2A1xx → ra2a1   (RA2 sub-family A1, Cortex-M23)
  * R7FA2E1xx → ra2e1
  * R7FA2L1xx → ra2l1
  * R7FA4M1xx → ra4m1   (RA4 sub-family M1, Cortex-M33)
  * R7FA4E1xx → ra4e1
  * R7FA4T1xx → ra4t1
  * R7FA4W1xx → ra4w1
  * R7FA6M1xx → ra6m1   (RA6 sub-family M1, Cortex-M33)
  * R7FA6T1xx → ra6t1
  * etc.

Per-chip device id = SVD basename, lowercased (R7FA6M5BH → r7fa6m5bh).

Usage::

    python3 scripts/bulk_re_emit_renesas_full.py \\
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


_RENESAS_RA_RX = re.compile(
    r"^r7f(?P<series>a)(?P<digit>\d)(?P<sub>[a-z])(?P<n>\d)",
    re.IGNORECASE,
)


def _device_id(svd_stem: str) -> str:
    return svd_stem.lower()


def _family_slug(device_id: str) -> str:
    """Derive a v2.1 family slug from the lowercased device id.

    R7FA2A1AB → ra2a1, R7FA4M1AB → ra4m1, R7FA6M5BH → ra6m5,
    R7FA6E10F → ra6e1 (last digit is package/feature variant).
    """
    m = _RENESAS_RA_RX.match(device_id)
    if m:
        # Compose: ra<digit><sub><n>
        return f"ra{m.group('digit')}{m.group('sub').lower()}{m.group('n')}"
    return device_id


def _re_emit_one(
    *,
    svd_path: Path,
    output_root: Path,
) -> tuple[Path, str]:
    device = _device_id(svd_path.stem)
    family = _family_slug(device)
    payload = svd_extract(
        vendor="renesas", family=family, device=device, svd_path=svd_path,
    )
    out_path = write_device_yaml(
        payload=payload, output_root=output_root,
        vendor="renesas", family=family, device=device,
    )
    return out_path, family


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svd-root", type=Path, required=True,
                        help="Root containing Renesas/ subdir "
                             "(usually <cache>/cmsis-svd-data/data)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--families", default="",
                        help="Comma-separated subset (default = every family)")
    args = parser.parse_args(argv)

    sub_dir = args.svd_root / "Renesas"
    if not sub_dir.is_dir():
        print(f"ERROR: {sub_dir} not present (sparse-checkout missing?)",
              file=sys.stderr)
        return 1
    svds = sorted(sub_dir.glob("*.svd"))
    if not svds:
        print(f"ERROR: no SVDs found under {sub_dir}", file=sys.stderr)
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
        print(f"  {status} {fam:8s} {ok:>3}/{len(rows):<3} chips")
        for path, success, msg in rows:
            if not success:
                print(f"      ✗ {path.stem}: {msg[:80]}")

    print()
    print(f"TOTAL: {grand_ok} ok, {grand_fail} failed across "
          f"{len(by_family)} family(ies)")
    return 1 if grand_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
