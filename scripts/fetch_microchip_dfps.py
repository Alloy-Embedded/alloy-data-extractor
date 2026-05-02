"""Auto-download Microchip DFP atpacks from packs.download.microchip.com.

Each ``.atpack`` is a ZIP with a per-pack layout:

  Microchip.SAMD21_DFP.3.8.270.atpack
    └─ samd21a/atdf/ATSAMD21E15A.atdf
    └─ samd21a/atdf/ATSAMD21E15B.atdf
    └─ ...
    └─ samd21a/include/...
    └─ package.content

We pick the highest semver per family and extract into
``<cache>/<family-slug>-<sha-fragment>/`` so multiple versions
coexist side-by-side (matching what the manual atpack extractor
produced for SAME70).

Usage::

    python3 scripts/fetch_microchip_dfps.py \\
        --cache /path/to/microchip-dfp \\
        SAMD21 SAMD51 SAML21 SAMV71

Pass family names without the ``Microchip.`` prefix or ``_DFP``
suffix.  Pass none to fetch the curated default Cortex-M list.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

INDEX_URL = "https://packs.download.microchip.com/"

# Default curated list — all the Cortex-M SAM lines worth covering
# (skips SAM9/A5/A7 Cortex-A MPUs, skips niche radio variants).
DEFAULT_FAMILIES = (
    # Cortex-M0+
    "SAMC20", "SAMC21",
    "SAMD09", "SAMD10", "SAMD11", "SAMD20", "SAMD21",
    "SAML10", "SAML11", "SAML21", "SAML22",
    "SAMR21", "SAMR30", "SAMR34", "SAMR35",
    "SAMHA1",
    # Cortex-M4F
    "SAMD51", "SAME51", "SAME53", "SAME54", "SAMG",
    # Cortex-M7
    "SAME70", "SAMS70", "SAMV70", "SAMV71",
    # Cortex-M3 (SAM3X, SAM4S etc. are published as separate
    # legacy packs; the modern pack catalogue stops at "SAMc/d/e/g/l/v")
)


_VERSION_RX = re.compile(r"\.(\d+)\.(\d+)\.(\d+)\.atpack$")
_PACK_RX = re.compile(
    r'Microchip\.(?P<fam>[A-Z0-9]+)_DFP\.(?P<ver>\d+\.\d+\.\d+)\.atpack',
)


def _semver_key(parts: tuple[str, ...]) -> tuple[int, int, int]:
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def _curl(url: str, timeout: int = 60) -> bytes:
    """Use system curl rather than urllib — the macOS python ships
    without a CA bundle so SSL verification fails for
    packs.download.microchip.com.  Curl uses the OS keystore."""
    result = subprocess.run(  # noqa: S603
        ["curl", "-fsSL", "--max-time", str(timeout), url],
        capture_output=True, check=True,
    )
    return result.stdout


def _discover_latest(family: str) -> str | None:
    """Return the filename of the highest-semver atpack for ``family``."""
    body = _curl(INDEX_URL, timeout=30).decode("utf-8", errors="replace")
    candidates = []
    for m in _PACK_RX.finditer(body):
        if m.group("fam") == family:
            candidates.append(m.group(0))
    if not candidates:
        return None
    candidates.sort(key=lambda name: _semver_key(_VERSION_RX.search(name).group(1, 2, 3)))  # type: ignore[union-attr]
    return candidates[-1]


def _atpack_dest_slug(family: str, atpack_path: Path) -> str:
    """Match the existing cache slug pattern ``<family-lower>-<sha-frag>``
    so the layout stays drop-in for the bulk script's
    ``--atdf-dir`` argument."""
    h = hashlib.sha1(atpack_path.read_bytes()).hexdigest()[:16]
    return f"{family.lower()}-{h}"


def fetch_family(family: str, cache_dir: Path) -> Path | None:
    """Download (if needed) and unzip the latest atpack for ``family``.

    Returns the destination directory containing the unpacked
    DFP.  ``None`` when discovery fails (network down, family
    name unknown, etc.).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    pack_name = _discover_latest(family)
    if pack_name is None:
        print(f"  ! {family}: no atpack found on packs.download.microchip.com")
        return None

    atpack_path = cache_dir / pack_name
    if not atpack_path.is_file():
        url = INDEX_URL + pack_name
        print(f"  ↓ {family}: downloading {pack_name}")
        atpack_path.write_bytes(_curl(url, timeout=300))
    else:
        print(f"  ✓ {family}: cached {pack_name}")

    slug = _atpack_dest_slug(family, atpack_path)
    dest = cache_dir / slug
    if dest.is_dir() and any(dest.rglob("*.atdf")):
        return dest

    if dest.is_dir():
        shutil.rmtree(dest)
    dest.mkdir()
    with zipfile.ZipFile(atpack_path) as z:
        z.extractall(dest)
    atdf_count = sum(1 for _ in dest.rglob("*.atdf"))
    print(f"    → unpacked into {slug}/  ({atdf_count} ATDF files)")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True,
                        help="Cache root (e.g. .../microchip-dfp/)")
    parser.add_argument("families", nargs="*",
                        help="Family names (SAMD21, SAML21, ...).  "
                             "Empty = curated default list.")
    args = parser.parse_args(argv)

    families = args.families or list(DEFAULT_FAMILIES)
    print(f"Fetching {len(families)} Microchip DFP family pack(s) into {args.cache}")
    print()

    failures = 0
    for fam in families:
        try:
            dest = fetch_family(fam, args.cache)
            if dest is None:
                failures += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ {fam}: {type(exc).__name__}: {exc}")

    print()
    print(f"{len(families) - failures}/{len(families)} families fetched")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
