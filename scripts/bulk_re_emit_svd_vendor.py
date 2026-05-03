"""Generic bulk-emit runner for any CMSIS-SVD vendor in
``cmsis-svd-data/data/<Vendor>/``.

Walks every ``.svd`` under the chosen vendor subdir and routes
through ``cmsis_svd_v2_1`` — same path as the STM, NXP, and
Renesas runners, but parameterised so we don't need a new script
per vendor.

Usage::

    python3 scripts/bulk_re_emit_svd_vendor.py \\
        --svd-root <cache>/cmsis-svd-data/data \\
        --vendor   infineon \\
        --svd-subdir Infineon \\
        --family-rule '^(?P<fam>[a-z]+\\d{2})\\d*$' \\
        --out      /path/to/alloy-devices-yml

``--family-rule`` is a Python regex applied to the lowercased
SVD basename (without ``.svd``); the named group ``fam`` becomes
the v2.1 family slug.  When no group named ``fam`` matches, the
full device id is used as the family slug (1-chip-per-family
fallback).
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


def _device_id(svd_stem: str) -> str:
    # Strip common decoration tokens.
    s = svd_stem.lower()
    for sep in ("_series", "_dfp", "_v"):
        if sep in s:
            s = s.split(sep, 1)[0]
    return s


def _family_slug(device_id: str, family_rx: re.Pattern[str] | None) -> str:
    if family_rx is None:
        return device_id
    m = family_rx.match(device_id)
    if m and m.groupdict().get("fam"):
        return m.group("fam")
    return device_id


def _re_emit_one(
    *, svd_path: Path, vendor: str,
    family_rx: re.Pattern[str] | None,
    output_root: Path,
) -> tuple[Path, str]:
    device = _device_id(svd_path.stem)
    family = _family_slug(device, family_rx)
    payload = svd_extract(
        vendor=vendor, family=family, device=device, svd_path=svd_path,
    )
    out_path = write_device_yaml(
        payload=payload, output_root=output_root,
        vendor=vendor, family=family, device=device,
    )
    return out_path, family


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svd-root", type=Path, required=True,
                        help="Root containing the vendor subdir "
                             "(usually <cache>/cmsis-svd-data/data)")
    parser.add_argument("--vendor", required=True,
                        help="v2.1 vendor slug (lowercase, e.g. "
                             "'infineon', 'nuvoton')")
    parser.add_argument("--svd-subdir", required=True,
                        help="Directory under --svd-root that holds the "
                             "vendor's SVDs (e.g. 'Infineon', 'Nuvoton')")
    parser.add_argument("--family-rule", default="",
                        help="Python regex against lowercased device id "
                             "with named group 'fam' for the family slug.  "
                             "Empty = 1 family per chip.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    sub_dir = args.svd_root / args.svd_subdir
    if not sub_dir.is_dir():
        print(f"ERROR: {sub_dir} not present (sparse-checkout missing?)",
              file=sys.stderr)
        return 1
    svds = sorted(sub_dir.glob("*.svd"))
    if not svds:
        print(f"ERROR: no SVDs found under {sub_dir}", file=sys.stderr)
        return 1

    family_rx = re.compile(args.family_rule) if args.family_rule else None

    print(f"Re-emitting {len(svds)} {args.vendor} chip(s) into {args.out}")
    print()

    failures = 0
    by_family: dict[str, list[tuple[Path, bool, str]]] = defaultdict(list)
    for svd in svds:
        try:
            out_path, fam = _re_emit_one(
                svd_path=svd, vendor=args.vendor,
                family_rx=family_rx, output_root=args.out,
            )
            by_family[fam].append((out_path, True, ""))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fam = _family_slug(_device_id(svd.stem), family_rx)
            by_family[fam].append((svd, False, f"{type(exc).__name__}: {exc}"))

    grand_ok = grand_fail = 0
    for fam in sorted(by_family):
        rows = by_family[fam]
        ok = sum(1 for r in rows if r[1])
        fail = len(rows) - ok
        grand_ok += ok
        grand_fail += fail
        marker = "✓" if fail == 0 else "⚠"
        print(f"  {marker} {fam:14s} {ok:>3}/{len(rows):<3} chips")
        for path, success, msg in rows:
            if not success:
                print(f"      ✗ {path.stem}: {msg[:80]}")

    print()
    print(f"TOTAL: {grand_ok} ok, {grand_fail} failed across "
          f"{len(by_family)} family(ies)")
    return 1 if grand_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
