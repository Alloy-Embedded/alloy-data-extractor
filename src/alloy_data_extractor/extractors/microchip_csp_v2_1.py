"""Microchip MPLAB Harmony CSP → v2.1 enrichment extractor.

Reads the per-family ``peripheral/clk_<chip>/config/clk.py`` from
the Microchip-MPLAB-Harmony/csp repository, extracts every register
+ bitfield that the Harmony Clock Manager configures, infers the
v2.1 ``clock.domains[]`` mapping from the Atmel naming convention,
and cross-references the bitfield's ``<value-group>`` from the
device ATDF to populate ``select_register.encoding`` /
``prescaler_register.encoding`` automatically.

This is the SAM/AVR equivalent of the STM32 CubeMX 5th source —
delivers v2.1 audit delta #11 (clock select_register encoding) and
delta #12 (clock domain mux/prescaler tables) without
hand-curating any encoding map: the encoding values come straight
from the ATDF ``<value-group>`` blocks; the (register, field) →
domain mapping is inferred from the symbol name.

The clk.py format itself is imperative Python that builds the
Harmony GUI configurator at runtime, so we don't execute it — we
just regex-extract the symbol declarations.  Pattern:

    clk_comp.createComboSymbol("PMC_MCKR_CSS", parent, …)
    clk_comp.createIntegerSymbol("PMC_CKGR_PLLAR_MULA", parent, …)
    clk_comp.createBooleanSymbol("CKGR_MOR_MOSCSEL", parent, …)

The first argument is always ``[<MODULE>_]<REGISTER>_<FIELD>`` —
we split on the rightmost ``_`` that lands on a known field name
and resolve register/field against the ATDF.

Output payload shape: a v2.1 enrichment overlay with only
``clock.domains[]`` populated.  Merges into the primary ATDF
payload through ``MICROCHIP_MERGE_POLICY`` exactly like the
overlay extractor does.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# clk.py symbol regex
# ---------------------------------------------------------------------------


# Three flavors of symbol creation: combo (mux selectors), integer
# (PLL/divider fields), boolean (enables / single-bit selects).
# The first arg is the symbol name like "PMC_MCKR_CSS".
_SYM_RX = re.compile(
    r"""create
        (?P<kind>Combo|Integer|Boolean|Hex|Long)
        Symbol\s*\(\s*
        ["'](?P<name>[A-Z0-9_]+)["']
    """,
    re.VERBOSE,
)


def _walk_clk_py(clk_path: Path) -> list[tuple[str, str]]:
    """Return list of ``(symbol_kind, symbol_name)`` from clk.py."""
    if not clk_path.is_file():
        return []
    text = clk_path.read_text(encoding="utf-8", errors="replace")
    return [(m.group("kind").lower(), m.group("name")) for m in _SYM_RX.finditer(text)]


# ---------------------------------------------------------------------------
# Symbol name → (register, field) resolver
# ---------------------------------------------------------------------------


def _split_symbol_name(
    sym_name: str,
    known_registers: set[str],
) -> tuple[str | None, str | None]:
    """``"PMC_MCKR_CSS"`` → ``("PMC_MCKR", "CSS")`` — choose the
    rightmost split that lands on a known register name.

    Harmony's symbol-name convention is ``[<MODULE>_]<REG>_<FIELD>``
    where ``<MODULE>`` is sometimes redundant with the register
    prefix (``"PMC_CKGR_MOR_MOSCSEL"`` — register is just ``CKGR_MOR``,
    not ``PMC_CKGR_MOR``).  We try every (start, cut) split, longest
    register match wins.
    """
    parts = sym_name.split("_")
    n = len(parts)
    best: tuple[str, str] | None = None
    for start in range(n - 1):
        for cut in range(start + 1, n):
            candidate_reg = "_".join(parts[start:cut])
            if candidate_reg not in known_registers:
                continue
            candidate_field = "_".join(parts[cut:])
            if not candidate_field:
                continue
            # Prefer longer register matches (most specific).
            if best is None or (cut - start) > len(best[0].split("_")):
                best = (candidate_reg, candidate_field)
    return best if best is not None else (None, None)


# ---------------------------------------------------------------------------
# ATDF value-group resolver (self-contained, no merge dependency)
# ---------------------------------------------------------------------------


def _atdf_register_index(atdf_root: ET.Element) -> set[str]:
    """All register names declared anywhere in the ATDF, uppercased
    for matching against the symbol-name parser."""
    out: set[str] = set()
    for reg in atdf_root.iter("register"):
        name = reg.get("name", "")
        if name:
            out.add(name.upper())
    return out


def _atdf_value_groups(atdf_root: ET.Element) -> dict[tuple[str, str], dict[str, int]]:
    """Resolve every ``<bitfield>`` whose ``values=`` attribute
    points at an in-module ``<value-group>``.  Returns
    ``{(REGISTER, FIELD): {value_name: int_value, ...}}`` for the
    fields that actually carry an enum.

    Used to populate ``clock.domains[].select_register.encoding``
    automatically — the encoding comes from the ATDF, not from a
    hand-maintained table.
    """
    # Build per-module {value_group_name → {name: int}}
    by_module: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    for module in atdf_root.iter("module"):
        mod_name = module.get("name", "")
        if not mod_name:
            continue
        for vg in module.iter("value-group"):
            vg_name = vg.get("name", "")
            if not vg_name:
                continue
            entries: dict[str, int] = {}
            for v in vg.iter("value"):
                name = v.get("name", "")
                raw = v.get("value", "")
                try:
                    entries[name.lower()] = int(raw, 0) if raw else 0
                except (TypeError, ValueError):
                    continue
            if entries:
                by_module[mod_name][vg_name] = entries

    # Walk every <register><bitfield> with values= and look up
    # which module owns the parent <register>.
    out: dict[tuple[str, str], dict[str, int]] = {}
    for module in atdf_root.iter("module"):
        mod_name = module.get("name", "")
        groups = by_module.get(mod_name, {})
        for reg in module.iter("register"):
            reg_name = reg.get("name", "").upper()
            if not reg_name:
                continue
            for bf in reg.iter("bitfield"):
                f_name = bf.get("name", "").upper()
                vg_ref = bf.get("values", "")
                if not f_name or not vg_ref:
                    continue
                enum = groups.get(vg_ref)
                if enum:
                    out[(reg_name, f_name)] = enum
    return out


# ---------------------------------------------------------------------------
# (register, field) → clock-domain inference
# ---------------------------------------------------------------------------


# Heuristic mapping from Atmel PMC/SUPC register naming to v2.1
# clock-domain ids.  The right column is the v2.1 domain id; the
# left column matches against the ATDF register name.  Order
# matters — first match wins.
_DOMAIN_INFERENCE: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # Slow Clock — SUPC_CR.XTALSEL toggles between RC32k and XTAL32k
    (re.compile(r"^SUPC_CR$"),         "slck",   "select"),
    (re.compile(r"^SUPC_MR$"),         "slck",   "select"),
    # Main Clock — CKGR_MOR.MOSCSEL between RC and external xtal
    (re.compile(r"^CKGR_MOR$"),        "mainck", "select"),
    # PLL — CKGR_PLLAR / CKGR_PLLBR / CKGR_UCKR (USB PLL)
    (re.compile(r"^CKGR_PLL[A-Z]R$"),  "plla",   "pll"),
    (re.compile(r"^CKGR_UCKR$"),       "upll",   "pll"),
    # Master Clock — PMC_MCKR.{CSS, PRES, MDIV}
    (re.compile(r"^PMC_MCKR$"),        "mck",    "select"),
    # Programmable Clocks — PMC_PCK0..7
    (re.compile(r"^PMC_PCK\d?$"),      "pck",    "select"),
    # Generic Peripheral Clocks — PMC_PCR.GCLKCSS
    (re.compile(r"^PMC_PCR$"),         "gclk",   "select"),
    # USB clock — PMC_USB.{USBS, USBDIV}
    (re.compile(r"^PMC_USB$"),         "usbck",  "select"),
    # Peripheral Clock Enable Registers — PMC_PCER0/PCER1 (gate, not select)
    (re.compile(r"^PMC_PCER\d?$"),     "periph", "gate"),
    (re.compile(r"^PMC_PCDR\d?$"),     "periph", "gate"),
)


def _infer_domain(reg_name: str) -> tuple[str, str] | None:
    """Map an ATDF register name to a v2.1 ``(domain_id, role)``
    where role is one of ``select`` / ``pll`` / ``gate``.  Returns
    ``None`` if the register isn't a known clock controller."""
    for pattern, domain, role in _DOMAIN_INFERENCE:
        if pattern.match(reg_name):
            return domain, role
    return None


# ---------------------------------------------------------------------------
# Build clock.domains[] from extracted symbols
# ---------------------------------------------------------------------------


def _build_clock_domains(
    symbols: list[tuple[str, str]],
    known_registers: set[str],
    enums: dict[tuple[str, str], dict[str, int]],
    register_module: dict[str, str],
) -> list[dict[str, Any]]:
    """Synthesise v2.1 ``clock.domains[]`` from the (kind, name)
    list extracted from clk.py.

    Each unique (domain, role) collects all (register, field)
    references; for ``select`` and ``pll`` roles we also fold in
    the value-group enum as ``select_register.encoding``.
    """
    # {(domain, role): [(register, field, kind), ...]}
    bucket: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for kind, sym_name in symbols:
        reg, field = _split_symbol_name(sym_name, known_registers)
        if not reg or not field:
            continue
        domain_role = _infer_domain(reg)
        if domain_role is None:
            continue
        key = (reg, field)
        if key in seen:
            continue
        seen.add(key)
        bucket[domain_role].append((reg, field, kind))

    domains: list[dict[str, Any]] = []
    # Field-name heuristics for splitting (select vs prescaler).
    _SELECT_FIELDS = {
        "css", "moscsel", "xtalsel", "src", "gclkcss", "usbs",
        "uplldiv2",
    }
    _PRESCALER_FIELDS = {
        "pres", "mdiv", "div", "diva", "divb", "usbdiv",
        "gclkdiv", "presa", "presb",
    }
    _PLL_INTEGER_FIELDS = {"mula", "mulb", "diva", "divb", "mul", "div"}

    for (domain, _role), bindings in bucket.items():
        # Bucket each (reg, field) by intent.  Priority for the
        # primary select_register slot:
        #   1. combo with enum + name in _SELECT_FIELDS
        #   2. boolean with enum + name in _SELECT_FIELDS
        #   3. any combo with enum
        select_candidates: list[tuple[str, str, str]] = []
        prescaler_candidates: list[tuple[str, str, str]] = []
        pll_candidates: list[tuple[str, str, str]] = []
        other: list[tuple[str, str, str]] = []
        for reg, field, kind in bindings:
            f_low = field.lower()
            if f_low in _SELECT_FIELDS:
                select_candidates.append((reg, field, kind))
            elif f_low in _PRESCALER_FIELDS:
                prescaler_candidates.append((reg, field, kind))
            elif f_low in _PLL_INTEGER_FIELDS:
                pll_candidates.append((reg, field, kind))
            else:
                other.append((reg, field, kind))

        domain_row: dict[str, Any] = {"id": domain}

        # Schema contract for clock.domains[*]:
        #   - id is required
        #   - sources OR source is required (anyOf)
        #   - select_register / prescaler_register both require
        #     `encoding` when present (additionalProperties:false)
        # We therefore only emit a domain when there's an encoded
        # select_register; integer divider fields (PLL DIVA/MULA,
        # PMC_USB.USBDIV) and boolean toggles (XTALSEL,
        # MOSCSEL=0/1) get dropped here — codegen recovers them
        # from templates.<ip>.fields[...] when it needs to.

        chosen_select: tuple[str, str, str] | None = None
        for cand in select_candidates:
            if (cand[0], cand[1]) in enums:
                chosen_select = cand
                break

        if chosen_select is None:
            continue

        sreg, sfield, _ = chosen_select
        module = register_module.get(sreg, "PMC")
        encoding = enums.get((sreg, sfield), {})
        domain_row["select_register"] = {
            "reg":      f"{module.upper()}.{sreg.upper()}",
            "field":    sfield.upper(),
            "encoding": encoding,
        }
        domain_row["sources"] = list(encoding.keys())

        # Prescaler — only when an enum-backed PRES/MDIV exists
        # (so the schema's required `encoding` is satisfied).
        for preg, pfield, _ in prescaler_candidates:
            if (preg, pfield) in enums:
                p_module = register_module.get(preg, "PMC")
                domain_row["prescaler_register"] = {
                    "reg":      f"{p_module.upper()}.{preg.upper()}",
                    "field":    pfield.upper(),
                    "encoding": enums[(preg, pfield)],
                }
                break

        domains.append(domain_row)
    return domains


def _atdf_register_module_index(atdf_root: ET.Element) -> dict[str, str]:
    """Map ``REGISTER_NAME → module_name`` so we know whether
    ``MCKR`` lives under module ``PMC`` or ``SUPC``."""
    out: dict[str, str] = {}
    for module in atdf_root.iter("module"):
        mod_name = module.get("name", "")
        if not mod_name:
            continue
        for reg in module.iter("register"):
            r = reg.get("name", "").upper()
            if r:
                out.setdefault(r, mod_name)
    return out


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


# Per-family CSP directory mapping — Microchip groups multiple
# chips under one clock pack.  Add families as we cover them.
_FAMILY_TO_CSP_DIR: dict[str, str] = {
    "same70":  "clk_sam_e70",
    "samv70":  "clk_sam_e70",   # V70 shares the E70 clock IP
    "samv71":  "clk_sam_e70",
    "sams70":  "clk_sam_e70",
    "samd21":  "clk_sam_d21",
    "samd20":  "clk_sam_d20",
    "samd51":  "clk_sam_d51_e51_e53_e54",
    "same51":  "clk_sam_d51_e51_e53_e54",
    "same53":  "clk_sam_d51_e51_e53_e54",
    "same54":  "clk_sam_d51_e51_e53_e54",
    "saml21":  "clk_sam_l21",
    "saml22":  "clk_sam_l22",
    "samc20":  "clk_sam_c20_c21",
    "samc21":  "clk_sam_c20_c21",
    "samg51":  "clk_sam_g51_g53_g54",
    "samg53":  "clk_sam_g51_g53_g54",
    "samg54":  "clk_sam_g51_g53_g54",
    "samg55":  "clk_sam_g55",
    "samd09":  "clk_sam_d09_d10_d11",
    "samd10":  "clk_sam_d09_d10_d11",
    "samd11":  "clk_sam_d09_d10_d11",
}


def extract_device(
    *,
    vendor: str,
    family: str,
    device: str,
    csp_root: Path,
    atdf_path: Path,
) -> dict[str, Any]:
    """Extract a v2.1 enrichment payload from one Harmony CSP
    clock pack + the device ATDF.

    Returns a payload with:

    * ``schema``    — bound to v2.1 const
    * ``identity``  — vendor/family/device echo
    * ``clock``     — one ``domains[]`` block synthesised from
                       Harmony's clk.py + ATDF value-groups

    Empty payload (only schema + identity) when the family has no
    CSP coverage — the merge engine treats it as a no-op.
    """
    csp_dir = _FAMILY_TO_CSP_DIR.get(family.lower())
    payload: dict[str, Any] = {
        "schema": "alloy.device.v2.1",
        "identity": {"vendor": vendor, "family": family, "device": device},
        # Carry the source-class tag so the merge engine recognises
        # which `clock.domains` priority slot this payload fills.
        # The merge engine takes the prefix before the first colon
        # as the canonical source-class id.
        "provenance": {
            "primary": f"microchip-csp:peripheral/{csp_dir or 'unknown'}/config/clk.py"
                       if csp_dir
                       else "microchip-csp:no-clock-pack",
        },
    }
    if csp_dir is None:
        return payload

    clk_path = csp_root / "peripheral" / csp_dir / "config" / "clk.py"
    if not clk_path.is_file():
        return payload

    if not atdf_path.is_file():
        return payload
    atdf_root = ET.parse(atdf_path).getroot()

    symbols = _walk_clk_py(clk_path)
    if not symbols:
        return payload

    known_registers = _atdf_register_index(atdf_root)
    enums = _atdf_value_groups(atdf_root)
    register_module = _atdf_register_module_index(atdf_root)

    domains = _build_clock_domains(
        symbols, known_registers, enums, register_module,
    )
    if domains:
        payload["clock"] = {"domains": domains}
    return payload


__all__ = ["extract_device"]
