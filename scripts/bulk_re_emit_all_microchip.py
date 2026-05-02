"""Bulk-emit every Microchip family present in the DFP cache.

Walks ``<cache>/microchip-dfp/<family>-<sha>/.../atdf/*.atdf``,
clusters by family slug, and runs the 3-source pipeline on each
cluster.  Replaces the shell-loop equivalent that broke on
paths with spaces.

Usage::

    python3 scripts/bulk_re_emit_all_microchip.py \\
        --dfp-cache <cache>/microchip-dfp \\
        --csp-root <cache>/microchip-csp \\
        --out /path/to/alloy-devices-yml \\
        [--families samc20,samg,...]

Pass ``--families`` to limit the run; otherwise every family
that has both an unpacked DFP directory AND a corresponding
``data/vendors/microchip/<fam>/family.toml`` overlay is processed.
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

from alloy_data_extractor.emit.canonical_yaml import write_device_yaml  # noqa: E402
from alloy_data_extractor.extractors.microchip_atdf_v2_1 import (  # noqa: E402
    extract_device as atdf_extract,
)
from alloy_data_extractor.extractors.microchip_csp_v2_1 import (  # noqa: E402
    extract_device as csp_extract,
)
from alloy_data_extractor.extractors.microchip_overlay_v2_1 import (  # noqa: E402
    extract_device as overlay_extract,
)
from alloy_data_extractor.merge_v2_1 import (  # noqa: E402
    MICROCHIP_MERGE_POLICY,
    merge_payloads,
)


_FAMILY_DIR_RX = re.compile(r"^(?P<family>[a-z][a-z0-9]+)-[0-9a-f]{16}$")


def _discover_atdfs(dfp_cache: Path) -> dict[str, list[Path]]:
    """Return ``{family_slug: [atdf_path, ...]}`` for every chip
    present under ``<dfp_cache>/<family>-<sha>/.../atdf/*.atdf``.
    Multiple sub-packs per family (e.g. samg/samg51 + samg/samg55)
    fold into one bucket per family slug."""
    out: dict[str, list[Path]] = defaultdict(list)
    for child in sorted(dfp_cache.iterdir()):
        if not child.is_dir():
            continue
        m = _FAMILY_DIR_RX.match(child.name)
        if not m:
            continue
        fam = m.group("family")
        for atdf in child.rglob("*.atdf"):
            out[fam].append(atdf)
    return out


def _re_emit_one(
    *,
    atdf_path: Path,
    family: str,
    overlay_root: Path,
    csp_root: Path | None,
    output_root: Path,
) -> tuple[Path, list[str]]:
    device = atdf_path.stem.lower()
    primary = atdf_extract(
        vendor="microchip", family=family, device=device, atdf_path=atdf_path,
    )
    sources = ["microchip-atdf"]
    enrichments = []

    family_toml = overlay_root / "vendors" / "microchip" / family / "family.toml"
    if family_toml.is_file():
        enrichments.append(overlay_extract(
            vendor="microchip", family=family, device=device,
            overlay_root=overlay_root,
        ))
        sources.append("microchip-overlay")

    if csp_root is not None and csp_root.is_dir():
        csp_payload = csp_extract(
            vendor="microchip", family=family, device=device,
            csp_root=csp_root, atdf_path=atdf_path,
        )
        if csp_payload.get("clock", {}).get("domains"):
            enrichments.append(csp_payload)
            sources.append("microchip-csp")

    result = merge_payloads(
        primary=primary, enrichments=tuple(enrichments),
        policy=MICROCHIP_MERGE_POLICY,
    )
    out_path = write_device_yaml(
        payload=result.payload, output_root=output_root,
        vendor="microchip", family=family, device=device,
    )
    return out_path, sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dfp-cache", type=Path, required=True)
    parser.add_argument("--csp-root", type=Path, default=None)
    parser.add_argument("--overlay-root", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--families", default="",
        help="Comma-separated subset (default = every family that has an "
             "overlay TOML + an unpacked DFP directory).",
    )
    args = parser.parse_args(argv)

    discovered = _discover_atdfs(args.dfp_cache)
    if not discovered:
        print(f"ERROR: no DFP family directories found under {args.dfp_cache}",
              file=sys.stderr)
        return 1

    if args.families:
        wanted = {f.strip() for f in args.families.split(",") if f.strip()}
        discovered = {f: a for f, a in discovered.items() if f in wanted}

    # Skip families without an overlay TOML — those need scaffolding first.
    runnable = {}
    skipped: list[str] = []
    for fam, atdfs in discovered.items():
        toml = args.overlay_root / "vendors" / "microchip" / fam / "family.toml"
        if not toml.is_file():
            skipped.append(fam)
            continue
        runnable[fam] = atdfs

    if skipped:
        print(f"  ! Skipping {len(skipped)} familie(s) without overlay TOML: "
              f"{', '.join(sorted(skipped))}")
        print()

    print(f"Re-emitting {sum(len(a) for a in runnable.values())} chip(s) "
          f"across {len(runnable)} family(ies) into {args.out}")
    print()

    grand_total_ok = 0
    grand_total_fail = 0
    for fam in sorted(runnable):
        atdfs = sorted(set(runnable[fam]), key=lambda p: p.stem.lower())
        # Dedupe by chip stem — multiple sub-packs may ship the same chip
        # (e.g. SAME70 has 3 versions of ATSAME70Q21B.atdf in the cache).
        seen: set[str] = set()
        unique_atdfs: list[Path] = []
        for a in atdfs:
            if a.stem.lower() in seen:
                continue
            seen.add(a.stem.lower())
            unique_atdfs.append(a)

        ok = fail = 0
        sources_used: set[str] = set()
        for atdf in unique_atdfs:
            try:
                out_path, sources = _re_emit_one(
                    atdf_path=atdf, family=fam,
                    overlay_root=args.overlay_root,
                    csp_root=args.csp_root,
                    output_root=args.out,
                )
                ok += 1
                sources_used.update(sources)
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print(f"    ✗ {atdf.stem.lower()}: "
                      f"{type(exc).__name__}: {str(exc)[:80]}")
        grand_total_ok += ok
        grand_total_fail += fail
        src_label = "+".join(s.removeprefix("microchip-") for s in sorted(sources_used))
        status = "✓" if fail == 0 else "⚠"
        print(f"  {status} {fam:10s} {ok:>3}/{len(unique_atdfs):<3} chips "
              f"(sources: {src_label})")

    print()
    print(f"TOTAL: {grand_total_ok} ok, {grand_total_fail} failed")
    return 1 if grand_total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
