"""Bulk-emit every Espressif ESP32 chip with the
``cmsis_svd_v2_1`` extractor.

Discovery walks ``<svd_root>/*.svd`` from the cached
``espressif-svd`` repo and routes every SVD through the existing
extractor.

Family-slug derivation:
  * esp32.svd          → family=esp32,    device=esp32
  * esp32c2.svd        → family=esp32c2,  device=esp32c2
  * esp32c3.svd        → family=esp32c3,  device=esp32c3
  * esp32c6.svd        → family=esp32c6,  device=esp32c6
  * esp32c6-lp.svd     → family=esp32c6,  device=esp32c6-lp   (LP processor)
  * esp32h2.svd        → family=esp32h2,  device=esp32h2
  * esp32p4.svd        → family=esp32p4,  device=esp32p4
  * esp32s2.svd        → family=esp32s2,  device=esp32s2
  * esp32s2-ulp.svd    → family=esp32s2,  device=esp32s2-ulp  (ULP coprocessor)
  * esp32s3.svd        → family=esp32s3,  device=esp32s3
  * esp32s3-ulp.svd    → family=esp32s3,  device=esp32s3-ulp

Existing hand-curated YAMLs (notably esp32-wroom32 module
variant + esp32 with package=qfn48 + memory rows) are
**preserved by default** — pass ``--force`` to overwrite.

Usage::

    python3 scripts/bulk_re_emit_espressif_full.py \\
        --svd-root <cache>/espressif-svd/svd \\
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


_COPROCESSOR_RX = re.compile(r"^(?P<parent>esp32[a-z0-9]+)-(?P<sub>ulp|lp)$")


def _device_id(svd_stem: str) -> str:
    return svd_stem.lower()


def _family_slug(device_id: str) -> str:
    """Return the parent family for a device id.  Coprocessor
    devices (esp32s2-ulp, esp32c6-lp) live under their parent
    chip's family directory."""
    m = _COPROCESSOR_RX.match(device_id)
    if m:
        return m.group("parent")
    return device_id


def _re_emit_one(
    *,
    svd_path: Path,
    output_root: Path,
    force: bool,
) -> tuple[Path | None, str, bool]:
    """Returns ``(out_path, family, was_written)``.  Returns
    ``out_path=None`` when the existing file is preserved and
    ``--force`` wasn't supplied."""
    device = _device_id(svd_path.stem)
    family = _family_slug(device)
    target = (
        output_root / "vendors" / "espressif" / family / "devices" / f"{device}.yml"
    )
    if target.exists() and not force:
        return target, family, False

    payload = svd_extract(
        vendor="espressif", family=family, device=device, svd_path=svd_path,
    )
    out_path = write_device_yaml(
        payload=payload, output_root=output_root,
        vendor="espressif", family=family, device=device,
    )
    return out_path, family, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svd-root", type=Path, required=True,
                        help="Root containing the Espressif SVDs "
                             "(usually <cache>/espressif-svd/svd)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing YAMLs (default: preserve "
                             "hand-curated chips)")
    parser.add_argument("--families", default="",
                        help="Comma-separated subset (default = every family)")
    args = parser.parse_args(argv)

    if not args.svd_root.is_dir():
        print(f"ERROR: {args.svd_root} not present", file=sys.stderr)
        return 1
    svds = sorted(args.svd_root.glob("*.svd"))
    if not svds:
        print(f"ERROR: no SVDs found under {args.svd_root}", file=sys.stderr)
        return 1

    if args.families:
        wanted = {f.strip() for f in args.families.split(",") if f.strip()}
        svds = [s for s in svds
                if _family_slug(_device_id(s.stem)) in wanted]

    print(f"Re-emitting {len(svds)} chip(s) into {args.out}")
    if not args.force:
        print("  (--force not set — existing YAMLs preserved)")
    print()

    failures = 0
    by_family: dict[str, list[tuple[Path, bool, bool, str]]] = defaultdict(list)
    for svd in svds:
        try:
            out_path, fam, written = _re_emit_one(
                svd_path=svd, output_root=args.out, force=args.force,
            )
            by_family[fam].append((out_path or svd, True, written, ""))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fam = _family_slug(_device_id(svd.stem))
            by_family[fam].append((svd, False, False, f"{type(exc).__name__}: {exc}"))

    grand_ok = grand_skipped = grand_fail = 0
    for fam in sorted(by_family):
        rows = by_family[fam]
        new_emit = sum(1 for r in rows if r[1] and r[2])
        skipped = sum(1 for r in rows if r[1] and not r[2])
        fail = sum(1 for r in rows if not r[1])
        grand_ok += new_emit
        grand_skipped += skipped
        grand_fail += fail
        marker = "✓" if fail == 0 else "⚠"
        info = []
        if new_emit:
            info.append(f"{new_emit} new")
        if skipped:
            info.append(f"{skipped} preserved")
        if fail:
            info.append(f"{fail} failed")
        print(f"  {marker} {fam:10s} {len(rows):>2} chip(s)  ({', '.join(info)})")
        for path, success, _written, msg in rows:
            if not success:
                print(f"      ✗ {path.stem}: {msg[:80]}")

    print()
    print(f"TOTAL: {grand_ok} new, {grand_skipped} preserved, "
          f"{grand_fail} failed across {len(by_family)} family(ies)")
    return 1 if grand_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
