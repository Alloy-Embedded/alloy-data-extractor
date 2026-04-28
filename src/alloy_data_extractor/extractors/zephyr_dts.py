"""Zephyr DTS extractor.

Self-contained mirror of the Zephyr-DTS adapter that lives in
alloy-codegen (where it was first added under
``ingest-zephyr-dts-as-source`` and later widened by
``extend-zephyr-dts-vendor-coverage``).  This module is the
extractor-side home of the same logic — per the architectural
pivot, vendor source parsers live in alloy-data-extractor and
the codegen consumes pre-extracted YAMLs.

Covers eight vendors today via per-vendor compatible-string
maps (Nordic, Renesas RA, TI CC13/CC26/CC32, Atmel SAM0,
Ambiq Apollo, Infineon XMC + PSoC6, SiLabs Gecko, Espressif
ESP32).  Adding a new vendor is one entry in
:data:`COMPATIBLE_MAPS`.

Public surface:

* :data:`COMPATIBLE_MAPS` — vendor → compatible-string → IP-name.
* :func:`compatible_map_for_vendor(vendor)` — merged with
  :data:`_GENERIC_COMPATIBLE_MAP` (ARM core peripherals).
* :func:`parse_zephyr_device_document(...)` — parse a DTS file
  into a :class:`ZephyrDeviceDocument` carrying peripherals,
  interrupts, and memory regions.
* :func:`extract_device(...)` — produce a canonical-IR-shaped
  payload ready for the canonical YAML writer.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devicetree import dtlib

# ---------------------------------------------------------------------------
# Compatible-string maps (one per vendor) + generic ARM-core map
# ---------------------------------------------------------------------------


_GENERIC_COMPATIBLE_MAP: dict[str, str] = {
    "arm,armv6m-nvic": "nvic",
    "arm,armv7m-nvic": "nvic",
    "arm,armv8m-nvic": "nvic",
    "arm,armv8.1m-nvic": "nvic",
    "arm,v6m-systick": "systick",
    "arm,v7m-systick": "systick",
    "arm,v8m-systick": "systick",
}


NORDIC_COMPATIBLE_MAP: dict[str, str] = {
    "nordic,nrf-uart": "uart",
    "nordic,nrf-uarte": "uart",
    "nordic,nrf-spi": "spi",
    "nordic,nrf-spim": "spi",
    "nordic,nrf-spis": "spi",
    "nordic,nrf-twi": "i2c",
    "nordic,nrf-twim": "i2c",
    "nordic,nrf-twis": "i2c",
    "nordic,nrf-saadc": "adc",
    "nordic,nrf-rtc": "rtc",
    "nordic,nrf-timer": "timer",
    "nordic,nrf-pwm": "pwm",
    "nordic,nrf-gpio": "gpio",
    "nordic,nrf-gpiote": "gpiote",
    "nordic,nrf-clock": "clock",
    "nordic,nrf-power": "power",
    "nordic,nrf-wdt": "watchdog",
    "nordic,nrf-temp": "temp_sensor",
    "nordic,nrf-rng": "rng",
    "nordic,nrf-ecb": "ecb",
    "nordic,nrf-egu": "egu",
    "nordic,nrf-radio": "radio",
}


RENESAS_RA_COMPATIBLE_MAP: dict[str, str] = {
    "renesas,ra-sci-uart": "uart",
    "renesas,ra-uart-sci-b": "uart",
    "renesas,ra-sci-i2c": "i2c",
    "renesas,ra-iic": "i2c",
    "renesas,ra-spi": "spi",
    "renesas,ra-spi-b": "spi",
    "renesas,ra-adc": "adc",
    "renesas,ra-gpt-pwm": "pwm",
    "renesas,ra-gpt-timer": "timer",
    "renesas,ra-agt-timer": "timer",
    "renesas,ra-ioport": "gpio",
    "renesas,ra-wdt": "watchdog",
    "renesas,ra-iwdt": "watchdog",
    "renesas,ra-cgc": "clock",
    "renesas,ra-dac": "dac",
    "renesas,ra-canfd": "can",
}


TI_COMPATIBLE_MAP: dict[str, str] = {
    "ti,cc13xx-cc26xx-uart": "uart",
    "ti,cc32xx-uart": "uart",
    "ti,stellaris-uart": "uart",
    "ti,cc13xx-cc26xx-spi": "spi",
    "ti,cc32xx-spi": "spi",
    "ti,cc13xx-cc26xx-i2c": "i2c",
    "ti,cc32xx-i2c": "i2c",
    "ti,cc13xx-cc26xx-adc": "adc",
    "ti,cc13xx-cc26xx-timer": "timer",
    "ti,cc13xx-cc26xx-timer-pwm": "pwm",
    "ti,cc13xx-cc26xx-gpio": "gpio",
    "ti,cc32xx-gpio": "gpio",
    "ti,cc13xx-cc26xx-watchdog": "watchdog",
    "ti,cc13xx-cc26xx-pinctrl": "pinctrl",
}


ATMEL_COMPATIBLE_MAP: dict[str, str] = {
    "atmel,sam0-uart": "uart",
    "atmel,sam0-spi": "spi",
    "atmel,sam0-i2c": "i2c",
    "atmel,sam0-adc": "adc",
    "atmel,sam0-tcc-pwm": "pwm",
    "atmel,sam0-tc32": "timer",
    "atmel,sam0-gpio": "gpio",
    "atmel,sam0-wdt": "watchdog",
    "atmel,sam0-rtc": "rtc",
    "atmel,sam0-dac": "dac",
    "atmel,sam0-trng": "rng",
    "atmel,sam0-can": "can",
}


AMBIQ_COMPATIBLE_MAP: dict[str, str] = {
    "ambiq,uart": "uart",
    "ambiq,iom": "i2c",
    "ambiq,spid": "spi",
    "ambiq,adc": "adc",
    "ambiq,ctimer": "timer",
    "ambiq,stimer": "timer",
    "ambiq,gpio": "gpio",
    "ambiq,wdt": "watchdog",
    "ambiq,mspi": "spi",
    "ambiq,rtc": "rtc",
}


INFINEON_COMPATIBLE_MAP: dict[str, str] = {
    "infineon,xmc4xxx-uart": "uart",
    "infineon,xmc4xxx-spi": "spi",
    "infineon,xmc4xxx-i2c": "i2c",
    "infineon,xmc4xxx-vadc": "adc",
    "infineon,xmc4xxx-ccu4-pwm": "pwm",
    "infineon,xmc4xxx-ccu4-timer": "timer",
    "infineon,xmc4xxx-gpio": "gpio",
    "infineon,xmc4xxx-wdt": "watchdog",
    "infineon,cat1-uart": "uart",
    "infineon,cat1-spi": "spi",
    "infineon,cat1-i2c": "i2c",
    "infineon,cat1-adc": "adc",
    "infineon,cat1-counter": "timer",
    "infineon,cat1-gpio": "gpio",
    "infineon,cat1-watchdog": "watchdog",
}


SILABS_COMPATIBLE_MAP: dict[str, str] = {
    "silabs,gecko-usart": "uart",
    "silabs,gecko-eusart": "uart",
    "silabs,gecko-leuart": "uart",
    "silabs,gecko-i2c": "i2c",
    "silabs,gecko-spi-usart": "spi",
    "silabs,gecko-iadc": "adc",
    "silabs,gecko-adc": "adc",
    "silabs,gecko-timer": "timer",
    "silabs,gecko-letimer": "timer",
    "silabs,gecko-pwm": "pwm",
    "silabs,gecko-gpio": "gpio",
    "silabs,gecko-wdog": "watchdog",
    "silabs,gecko-rtcc": "rtc",
    "silabs,gecko-trng": "rng",
}


ESPRESSIF_COMPATIBLE_MAP: dict[str, str] = {
    "espressif,esp32-uart": "uart",
    "espressif,esp32-usb-serial": "uart",
    "espressif,esp32-spi": "spi",
    "espressif,esp32-i2c": "i2c",
    "espressif,esp32-adc": "adc",
    "espressif,esp32-mcpwm": "pwm",
    "espressif,esp32-ledc": "pwm",
    "espressif,esp32-timer": "timer",
    "espressif,esp32-rtc-timer": "timer",
    "espressif,esp32-gpio": "gpio",
    "espressif,esp32-watchdog": "watchdog",
    "espressif,esp32-rmt": "rmt",
    "espressif,esp32-twai": "can",
    "espressif,esp32-dac": "dac",
}


COMPATIBLE_MAPS: dict[str, dict[str, str]] = {
    "nordic": NORDIC_COMPATIBLE_MAP,
    "renesas": RENESAS_RA_COMPATIBLE_MAP,
    "ti": TI_COMPATIBLE_MAP,
    "atmel": ATMEL_COMPATIBLE_MAP,
    "ambiq": AMBIQ_COMPATIBLE_MAP,
    "infineon": INFINEON_COMPATIBLE_MAP,
    "silabs": SILABS_COMPATIBLE_MAP,
    "espressif": ESPRESSIF_COMPATIBLE_MAP,
}


def compatible_map_for_vendor(vendor: str) -> dict[str, str]:
    """Return the merged compatible map for a vendor.

    Result = generic ARM-core map + vendor-specific map (vendor
    map wins on conflict).  Raises ``ValueError`` for unknown
    vendor keys, listing the registered vendors so the caller
    sees the available options.
    """
    mapping = COMPATIBLE_MAPS.get(vendor)
    if mapping is None:
        raise ValueError(
            f"unknown vendor {vendor!r}.  "
            f"Known vendors: {sorted(COMPATIBLE_MAPS)}"
        )
    return {**_GENERIC_COMPATIBLE_MAP, **mapping}


# ---------------------------------------------------------------------------
# DTS parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZephyrDtsMemoryRegion:
    name: str
    base_address: int
    size_bytes: int
    compatible: str


@dataclass(frozen=True, slots=True)
class ZephyrDtsPeripheral:
    name: str
    base_address: int
    compatible: str
    ip_name: str


@dataclass(frozen=True, slots=True)
class ZephyrDtsInterrupt:
    name: str
    line: int
    peripheral: str | None


@dataclass(frozen=True, slots=True)
class ZephyrDeviceDocument:
    device_name: str
    peripherals: tuple[ZephyrDtsPeripheral, ...] = field(default_factory=tuple)
    interrupts: tuple[ZephyrDtsInterrupt, ...] = field(default_factory=tuple)
    memories: tuple[ZephyrDtsMemoryRegion, ...] = field(default_factory=tuple)
    skipped_compatibles: tuple[str, ...] = field(default_factory=tuple)


_INSTANCE_LABEL_RE = re.compile(r"^([a-z]+)(\d+)$")


def peripheral_instance_index(label: str | None, fallback_name: str) -> int:
    target = label or fallback_name
    match = _INSTANCE_LABEL_RE.match(target.lower())
    return int(match.group(2)) if match else 0


def _read_compat(node: dtlib.Node) -> tuple[str, ...]:
    prop = node.props.get("compatible")
    return tuple(prop.to_strings()) if prop is not None else ()


def _read_reg_pairs(node: dtlib.Node) -> tuple[tuple[int, int], ...]:
    prop = node.props.get("reg")
    if prop is None:
        return ()
    nums = prop.to_nums()
    if len(nums) % 2 != 0:
        return ()
    return tuple((nums[i], nums[i + 1]) for i in range(0, len(nums), 2))


def _read_interrupts(node: dtlib.Node) -> tuple[tuple[int, int], ...]:
    prop = node.props.get("interrupts")
    if prop is None:
        return ()
    nums = prop.to_nums()
    if len(nums) % 2 != 0:
        return ()
    return tuple((nums[i], nums[i + 1]) for i in range(0, len(nums), 2))


def _node_label(node: dtlib.Node) -> str | None:
    return node.labels[0] if node.labels else None


def _peripheral_canonical_name(label: str | None, fallback_name: str) -> str:
    return (label or fallback_name).upper()


def preprocess_dtsi(
    dtsi_path: Path,
    *,
    zephyr_root: Path | None = None,
    extra_includes: tuple[Path, ...] = (),
    vendor_hint: str | None = None,
) -> str:
    """Run cpp on a Zephyr `.dtsi` file and return the
    preprocessed DTS text (with `/dts-v1/;` prepended) so dtlib
    can parse it.

    Zephyr `.dtsi` files use ``#include`` directives that need
    C-preprocessor expansion before dtlib accepts them.  When
    ``zephyr_root`` is provided we add the canonical include
    paths (``dts/`` + ``include/``).
    """
    import subprocess

    # Use clang -E in assembler-with-cpp mode: this preserves
    # DTS-specific tokens like ``#address-cells = <1>;`` (which
    # plain C-mode preprocessing misreads as a preprocessor
    # directive) while still expanding ``#include`` directives.
    # ``-P`` suppresses ``# <line> <file>`` markers.
    cmd: list[str] = [
        "clang",
        "-E",
        "-P",
        "-x",
        "assembler-with-cpp",
        str(dtsi_path),
    ]
    include_dirs: list[Path] = list(extra_includes)
    if zephyr_root is not None:
        # Per-arch include dirs: chip-variant `.dtsi` files
        # commonly include `<nordic/nrf52832.dtsi>` and similar,
        # which resolve relative to `dts/<arch>/`.  We add every
        # arch directory we find so the resolver picks the right
        # base file regardless of which architecture the chip is.
        dts_root = zephyr_root / "dts"
        include_dirs.append(dts_root / "common")
        include_dirs.append(dts_root / "vendor")
        for arch_dir in sorted(dts_root.glob("*")):
            if arch_dir.is_dir() and arch_dir.name not in {"bindings", "common", "vendor"}:
                include_dirs.append(arch_dir)
        include_dirs.extend(
            [
                dts_root,
                zephyr_root / "include",
                zephyr_root / "include" / "zephyr",
                zephyr_root / "include" / "zephyr" / "dt-bindings",
                dts_root / "bindings",
            ]
        )
        # Force-include `mem.h` so naked `DT_SIZE_K(...)` /
        # `DT_SIZE_M(...)` macros expand even when the .dtsi
        # under inspection forgot to `#include <mem.h>`.
        common_mem = dts_root / "common" / "mem.h"
        if common_mem.exists():
            cmd.extend(["-imacros", str(common_mem)])
        # Force-include vendor-common headers so vendor-specific
        # macros (e.g. ``NRF_DEFAULT_IRQ_PRIORITY``) expand even
        # when the chip-variant .dtsi forgot the parent include.
        if vendor_hint:
            for candidate in (
                dts_root / "vendor" / vendor_hint / f"{vendor_hint}_common.dtsi",
                dts_root / "vendor" / vendor_hint / "nrf_common.dtsi",
            ):
                if candidate.exists():
                    cmd.extend(["-imacros", str(candidate)])
                    break
    for inc in include_dirs:
        cmd.append(f"-I{inc}")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0:
        raise ValueError(
            f"clang -E preprocessing failed for {dtsi_path}: {result.stderr.strip()[:300]}"
        )
    body = result.stdout
    if "/dts-v1/;" not in body:
        body = "/dts-v1/;\n" + body
    return body


def _stub_undefined_labels(body: str) -> str:
    """Make a fragment-style Zephyr `.dtsi` parseable by
    dtlib by wrapping/stubbing as needed.

    Chip-variant `.dtsi` files in Zephyr are partial: they
    contain overlay blocks (``&label { ... };``) and/or
    bare top-level node declarations (``ipc0: ipc0 { ... };``)
    that only make sense when concatenated with their parent
    SoC tree.  This function:

    * Injects empty ``<label>: stub@addr { reg = ... };``
      stubs for any ``&<label>`` reference whose definition
      is missing — silences ``DTError: undefined node label``.
    * Wraps any bare top-level node declarations in a
      synthetic ``/ { ... };`` root so the parser sees a
      well-formed tree.  Overlay ``&label { }`` blocks are
      LEFT outside the root (they're valid at top level).
    """
    import re

    # Strip /dts-v1/; for processing, re-add at the end.
    has_dts_v1 = "/dts-v1/;" in body
    if has_dts_v1:
        body = body.replace("/dts-v1/;", "", 1)

    # Find every `&<label>` reference + every `<label>:` definition.
    referenced = set(re.findall(r"&([A-Za-z_][A-Za-z0-9_]*)", body))
    defined = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:", body))
    missing = sorted(referenced - defined)

    # Build stub root: holds all undefined-label stubs plus,
    # when there's no `/ { }` already, gathers any orphan
    # top-level node declarations like `ipc0: ipc0 { ... };`.
    has_root_section = bool(re.search(r"^\s*/\s*\{", body, flags=re.MULTILINE))

    stub_lines = ["/ {"]
    for label in missing:
        stub_lines.append(
            f"    {label}: stub_{label}@deadbeef {{ reg = <0xdeadbeef 0>; }};"
        )

    if not has_root_section:
        # Pull out top-level `name: name@addr { ... };` blocks
        # (orphan declarations at file scope) and move them
        # into the stub root.  Leaves overlay `&label { ... };`
        # blocks alone — they're valid at top level.
        orphan_blocks: list[str] = []

        def _extract_orphans(text: str) -> tuple[str, list[str]]:
            out: list[str] = []
            new_text_parts: list[str] = []
            pos = 0
            while pos < len(text):
                # Search for a top-level `LABEL [LABEL2: ...] NAME ... {` declaration.
                # DTS allows multiple labels before a node name:
                #   `dppic0: dppic: dppic@17000 { ... };`
                m = re.search(
                    r"^([A-Za-z_][A-Za-z0-9_]*\s*:\s*)+[A-Za-z_][A-Za-z0-9_@,-]*\s*\{",
                    text[pos:],
                    re.MULTILINE,
                )
                if m is None:
                    new_text_parts.append(text[pos:])
                    break
                start = pos + m.start()
                new_text_parts.append(text[pos:start])
                # Walk braces to find the matching `};`.
                brace_pos = pos + m.end() - 1
                depth = 1
                i = brace_pos + 1
                while i < len(text) and depth > 0:
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                    i += 1
                # Skip the trailing `;` if present.
                while i < len(text) and text[i] in (";", "\n", " ", "\t"):
                    if text[i] == ";":
                        i += 1
                        break
                    i += 1
                out.append(text[start:i])
                pos = i
            return "".join(new_text_parts), out

        body, orphan_blocks = _extract_orphans(body)
        for block in orphan_blocks:
            # Indent the orphan block 4 spaces for readability.
            indented = "\n".join("    " + line for line in block.splitlines())
            stub_lines.append(indented)

    stub_lines.append("};")
    stub = "\n".join(stub_lines) + "\n"

    head = "/dts-v1/;\n" if has_dts_v1 else ""
    return head + stub + body


def parse_zephyr_device_document(
    dts_path: Path,
    *,
    compatible_map: dict[str, str],
    extra_compatible_filter: Callable[[str], bool] | None = None,
    zephyr_root: Path | None = None,
    vendor_hint: str | None = None,
) -> ZephyrDeviceDocument:
    """Parse one DTS file into a structural document.

    ``compatible_map`` maps Zephyr ``compatible`` strings to alloy
    canonical IP names.  Nodes whose first compatible is not in
    the map are silently skipped — DTS is intentionally permissive
    about new compatibles upstream.
    """
    if not dts_path.exists():
        raise FileNotFoundError(f"DTS file not found: {dts_path}")

    # Decide whether to preprocess: a `.dtsi` (or any DTS that
    # uses `#include`) needs cpp expansion before dtlib will
    # accept it.  When `zephyr_root` is provided, run cpp via
    # `preprocess_dtsi`; otherwise fall back to direct dtlib.DT.
    needs_preprocess = (
        dts_path.suffix == ".dtsi"
        or (zephyr_root is not None and "#include" in dts_path.read_text(encoding="utf-8"))
    )
    if needs_preprocess and zephyr_root is not None:
        body = preprocess_dtsi(
            dts_path, zephyr_root=zephyr_root, vendor_hint=vendor_hint
        )
        body = _stub_undefined_labels(body)
        # dtlib.DT only takes a path; write the preprocessed body
        # to a temp file alongside the original.
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".dts", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        try:
            # ``force=True``: chip-variant `.dtsi` files are
            # fragments meant to be merged with a parent SoC
            # tree; on their own they may reference labels
            # defined elsewhere (e.g. ``&sram0_shared``,
            # ``&eefc``).  ``force`` lets dtlib swallow those
            # reference errors so we still extract the
            # peripherals the fragment DOES define.
            dt = dtlib.DT(str(tmp_path), force=True)
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        dt = dtlib.DT(str(dts_path), force=True)
    peripherals: list[ZephyrDtsPeripheral] = []
    interrupts: list[ZephyrDtsInterrupt] = []
    memories: list[ZephyrDtsMemoryRegion] = []
    skipped: set[str] = set()

    memory_compatibles = {
        "mmio-sram",
        "soc-nv-flash",
        "zephyr,memory-region",
        "fixed-partitions",
    }

    # ``dt.root`` may be ``None`` when ``.dtsi`` carries only
    # overlay-style ``&label { ... }`` blocks (no ``/ { ... }``
    # root section).  In that case we have nothing to extract;
    # return an empty document so the caller surfaces a
    # zero-peripheral payload rather than crashing.
    if dt.root is None:
        return ZephyrDeviceDocument(
            device_name=dts_path.stem.lower(),
            peripherals=(),
            interrupts=(),
            memories=(),
            skipped_compatibles=(),
        )

    for node in dt.root.node_iter():
        compatibles = _read_compat(node)
        if not compatibles:
            continue
        first = compatibles[0]

        if (
            first in memory_compatibles
            or any(c in memory_compatibles for c in compatibles)
            or "memory" in node.name
            or "flash" in node.name
        ):
            for base, size in _read_reg_pairs(node):
                memories.append(
                    ZephyrDtsMemoryRegion(
                        name=_node_label(node) or node.name,
                        base_address=base,
                        size_bytes=size,
                        compatible=first,
                    )
                )
            continue

        if first in ("simple-bus", "syscon"):
            continue

        ip_name = compatible_map.get(first)
        if ip_name is None:
            if extra_compatible_filter is not None and extra_compatible_filter(first):
                ip_name = first.split(",", 1)[-1].replace("-", "_")
            else:
                skipped.add(first)
                continue

        reg_pairs = _read_reg_pairs(node)
        if not reg_pairs:
            continue
        base_address = reg_pairs[0][0]
        label = _node_label(node)
        peripheral_name = _peripheral_canonical_name(label, node.name)
        peripherals.append(
            ZephyrDtsPeripheral(
                name=peripheral_name,
                base_address=base_address,
                compatible=first,
                ip_name=ip_name,
            )
        )

        for line, _priority in _read_interrupts(node):
            del _priority
            interrupts.append(
                ZephyrDtsInterrupt(
                    name=f"{peripheral_name}_IRQ",
                    line=line,
                    peripheral=peripheral_name,
                )
            )

    peripherals.sort(key=lambda p: (p.base_address, p.name))
    interrupts.sort(key=lambda i: (i.line, i.name))
    memories.sort(key=lambda m: (m.base_address, m.name))

    return ZephyrDeviceDocument(
        device_name=dts_path.stem.lower(),
        peripherals=tuple(peripherals),
        interrupts=tuple(interrupts),
        memories=tuple(memories),
        skipped_compatibles=tuple(sorted(skipped)),
    )


# ---------------------------------------------------------------------------
# Canonical-IR-shaped extraction (mirrors cmsis_svd.extract_device)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZephyrDtsExtraction:
    payload: dict[str, Any]
    provenance: dict[str, str]


def _content_revision(dts_path: Path) -> str:
    digest = hashlib.sha256(dts_path.read_bytes())
    return f"content-sha256:{digest.hexdigest()[:16]}"


# Per-(vendor, family) core hint for Zephyr-sourced chips.  DTS
# does carry CPU info via `compatible = "arm,cortex-mX"` but the
# extractor doesn't surface it yet — this table is a fallback so
# the canonical YAML always has identity.core populated.
_ZEPHYR_FAMILY_TO_CORE: dict[tuple[str, str], str] = {
    ("nordic", "nrf51"): "cortex-m0",
    ("nordic", "nrf52"): "cortex-m4f",
    ("nordic", "nrf53"): "cortex-m33",
    ("nordic", "nrf54l"): "cortex-m33",
    ("nordic", "nrf91"): "cortex-m33",
    ("renesas", "ra"): "cortex-m4f",
    ("renesas", "ra2"): "cortex-m23",
    ("renesas", "ra4"): "cortex-m33",
    ("renesas", "ra6"): "cortex-m33",
    ("ti", "cc13xx"): "cortex-m4f",
    ("ti", "cc26xx"): "cortex-m4f",
    ("ti", "cc32xx"): "cortex-m4f",
    ("atmel", "sam"): "cortex-m4f",
    ("atmel", "samd"): "cortex-m0plus",
    ("atmel", "saml"): "cortex-m0plus",
    ("atmel", "same"): "cortex-m7f",
    ("atmel", "samv"): "cortex-m7f",
    ("ambiq", "apollo"): "cortex-m4f",
    ("ambiq", "apollo3"): "cortex-m4f",
    ("ambiq", "apollo4"): "cortex-m4f",
    ("infineon", "xmc"): "cortex-m4f",
    ("infineon", "psoc6"): "cortex-m4f",
    ("infineon", "cat1"): "cortex-m4f",
    ("silabs", "gecko"): "cortex-m4f",
    ("silabs", "efr32"): "cortex-m33",
    ("silabs", "efm32"): "cortex-m4f",
    ("espressif", "esp32-xtensa"): "xtensa-lx6",
}


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    svd_path: Path,
    revision: str | None = None,
    schema_version: str = "1.2.0",
    zephyr_root: Path | None = None,
) -> ZephyrDtsExtraction:
    """Extract one device from a Zephyr DTS file.

    Signature mirrors ``cmsis_svd.extract_device`` so the
    pipeline registry can dispatch uniformly.  ``svd_path`` is
    the DTS file path (kept as-is for argument-name parity).
    ``zephyr_root`` is needed when ``svd_path`` is a `.dtsi`
    that uses ``#include`` directives — cpp preprocessing
    walks the Zephyr include tree.
    """
    if not svd_path.exists():
        raise FileNotFoundError(f"DTS file not found: {svd_path}")
    compatible_map = compatible_map_for_vendor(vendor)
    document = parse_zephyr_device_document(
        svd_path,
        compatible_map=compatible_map,
        zephyr_root=zephyr_root,
        vendor_hint=vendor,
    )

    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "identity": {
            "vendor": vendor,
            "family": family,
            "device": device,
            "package": "",
            "core": _ZEPHYR_FAMILY_TO_CORE.get((vendor, family), ""),
            "summary": f"Admitted via Zephyr DTS ({svd_path.name}).",
        },
        "provenance": {
            "source_id": "zephyr-dts",
            "source_path": str(svd_path),
            "patch_ids": [],
        },
        "memories": [
            {
                "name": m.name,
                "base_address": m.base_address,
                "size_bytes": m.size_bytes,
                "compatible": m.compatible,
            }
            for m in document.memories
        ],
        "peripherals": [
            {
                "name": p.name,
                "base_address": p.base_address,
                "compatible": p.compatible,
                "ip_name": p.ip_name,
            }
            for p in document.peripherals
        ],
        "interrupts": [
            {"name": i.name, "line": i.line, "peripheral": i.peripheral}
            for i in document.interrupts
        ],
    }

    return ZephyrDtsExtraction(
        payload=payload,
        provenance={
            "source_id": "zephyr-dts",
            "revision": revision or _content_revision(svd_path),
            "source_path": str(svd_path),
        },
    )


# ---------------------------------------------------------------------------
# Extractor protocol adapter (added by define-extractor-protocol)
# ---------------------------------------------------------------------------


from alloy_data_extractor.extractor_protocol import (  # noqa: E402
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)

# Family bindings for the Zephyr-DTS extractor.  Every vendor in
# COMPATIBLE_MAPS gets at least one family registered so the
# resolver / bulk pipeline can route DTS-sourced chips through
# this extractor.  Family naming follows Zephyr's tree
# structure (`dts/<arch>/<vendor>/<device>.dtsi`) — the vendor
# here is the alloy-vendor key, families are loose buckets that
# bulk discovery uses for routing.
_ZEPHYR_DTS_FAMILIES: tuple[tuple[str, str], ...] = (
    ("nordic", "nrf52"),
    ("nordic", "nrf51"),
    ("nordic", "nrf53"),
    ("nordic", "nrf54l"),
    ("nordic", "nrf91"),
    ("renesas", "ra"),
    ("renesas", "ra2"),
    ("renesas", "ra4"),
    ("renesas", "ra6"),
    ("ti", "cc13xx"),
    ("ti", "cc26xx"),
    ("ti", "cc32xx"),
    ("atmel", "sam"),
    ("atmel", "samd"),
    ("atmel", "saml"),
    ("atmel", "same"),
    ("atmel", "samv"),
    ("ambiq", "apollo"),
    ("ambiq", "apollo3"),
    ("ambiq", "apollo4"),
    ("infineon", "xmc"),
    ("infineon", "psoc6"),
    ("infineon", "cat1"),
    ("silabs", "gecko"),
    ("silabs", "efr32"),
    ("silabs", "efm32"),
    ("espressif", "esp32-xtensa"),
)


@register_extractor(
    "zephyr-dts",
    families=_ZEPHYR_DTS_FAMILIES,
)
class ZephyrDtsExtractor:
    """The :class:`Extractor` adapter for the Zephyr-DTS parser.

    Bound family-by-family because not every vendor whose
    compatible-strings are mapped here has been admitted yet —
    admission requires a registered codegen-side IR build path
    too, which is its own decision.
    """

    extractor_id: str = "zephyr-dts"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        dts_path = request.require_source("zephyr-dts")
        zephyr_root = request.source_paths.get("zephyr-root")
        legacy = extract_device(
            vendor=request.vendor,
            family=request.family,
            device=request.device,
            svd_path=dts_path,
            revision=request.revision,
            zephyr_root=zephyr_root,
        )
        return ExtractionResult(
            payload=legacy.payload,
            provenance=ProvenanceRecord(
                source_id="zephyr-dts",
                source_path=str(dts_path),
                revision=request.revision,
            ),
            warnings=(),
        )


__all__ = [
    "AMBIQ_COMPATIBLE_MAP",
    "ATMEL_COMPATIBLE_MAP",
    "COMPATIBLE_MAPS",
    "ESPRESSIF_COMPATIBLE_MAP",
    "INFINEON_COMPATIBLE_MAP",
    "NORDIC_COMPATIBLE_MAP",
    "RENESAS_RA_COMPATIBLE_MAP",
    "SILABS_COMPATIBLE_MAP",
    "TI_COMPATIBLE_MAP",
    "ZephyrDeviceDocument",
    "ZephyrDtsExtraction",
    "ZephyrDtsExtractor",
    "ZephyrDtsInterrupt",
    "ZephyrDtsMemoryRegion",
    "ZephyrDtsPeripheral",
    "compatible_map_for_vendor",
    "extract_device",
    "parse_zephyr_device_document",
    "peripheral_instance_index",
]
