"""Datasheet PDF scraper — `add-modm-data-pdf-extractor`
(Phase 4.1).

Last-resort coverage for chips whose vendor publishes no
machine-readable source.  Approach: pdfminer.six text
extraction + per-vendor template-driven scraping.

Confidence contract: every YAML produced here MUST carry
``provenance.confidence: low``.  Codegen consumers MUST opt-in
via ``--accept-low-confidence`` to load these.

Template format (TOML):

```toml
# data/datasheet_templates/<vendor>.toml
[memory_map]
# Each entry maps a label to a regex with named groups
# `base` (hex) and `size` (int).
flash = "Flash memory.*?(?P<base>0x[0-9a-fA-F]+).*?(?P<size>\\d+) ?KB"

[peripheral]
# Section headers introducing peripheral pages; the scraper
# emits one peripheral row per match.
uart = "UART(?P<index>\\d+).*?Base address: (?P<base>0x[0-9a-fA-F]+)"
```

This v1 implementation supports `[memory_map]` and
`[peripheral]` template sections — enough to stand up a
proof-of-life Holtek HT32 / 8051-derivative chip without a
SVD/ATDF.  Register-tree scraping (the modm-data style
table-recognition pipeline) is a follow-up.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    ProvenanceRecord,
    register_extractor,
)


@dataclass(frozen=True, slots=True)
class DatasheetTemplate:
    """One vendor's PDF scraping template."""

    vendor: str
    memory_map: dict[str, re.Pattern[str]]
    peripherals: dict[str, re.Pattern[str]]


def load_template(template_path: Path, *, vendor: str) -> DatasheetTemplate:
    raw = tomllib.loads(template_path.read_text(encoding="utf-8"))
    mem = {
        name: re.compile(pat, re.IGNORECASE | re.DOTALL)
        for name, pat in (raw.get("memory_map") or {}).items()
    }
    peri = {
        name: re.compile(pat, re.IGNORECASE | re.DOTALL)
        for name, pat in (raw.get("peripheral") or {}).items()
    }
    return DatasheetTemplate(vendor=vendor, memory_map=mem, peripherals=peri)


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract plain text from a PDF.  Pure pdfminer.six —
    no LLM, no OCR.
    """
    from pdfminer.high_level import extract_text  # type: ignore[import-untyped]

    return extract_text(str(pdf_path))


def _parse_int_size(text: str) -> int | None:
    """Convert a human-readable size string ("128 KB", "32 KiB",
    "1024") into bytes.  None if unparseable."""
    text = text.strip()
    match = re.match(r"^(\d+)\s*(K|Ki|M|Mi|G|Gi)?B?$", text, re.IGNORECASE)
    if not match:
        try:
            return int(text)
        except ValueError:
            return None
    value = int(match.group(1))
    unit = (match.group(2) or "").lower()
    multipliers = {
        "": 1,
        "k": 1024,
        "ki": 1024,
        "m": 1024 * 1024,
        "mi": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
        "gi": 1024 * 1024 * 1024,
    }
    return value * multipliers[unit]


def _scrape_memory_map(text: str, template: DatasheetTemplate) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, pattern in template.memory_map.items():
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        base_hex = groups.get("base")
        size_str = groups.get("size")
        if base_hex is None or size_str is None:
            continue
        try:
            base = int(base_hex, 16)
        except ValueError:
            continue
        size = _parse_int_size(size_str) or 0
        rows.append({"name": name, "base_address": base, "size_bytes": size})
    rows.sort(key=lambda r: r["base_address"])
    return rows


def _scrape_peripherals(text: str, template: DatasheetTemplate) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, pattern in template.peripherals.items():
        for match in pattern.finditer(text):
            groups = match.groupdict()
            base_hex = groups.get("base")
            if base_hex is None:
                continue
            try:
                base = int(base_hex, 16)
            except ValueError:
                continue
            index = groups.get("index", "")
            name = f"{kind.upper()}{index}".strip()
            rows.append(
                {
                    "name": name,
                    "base_address": base,
                    "kind": kind,
                }
            )
    # Dedup by (name, base_address) and sort.
    seen: set[tuple[str, int]] = set()
    deduped: list[dict[str, Any]] = []
    for r in rows:
        key = (r["name"], r["base_address"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    deduped.sort(key=lambda r: (r["base_address"], r["name"]))
    return deduped


def scrape_datasheet(pdf_path: Path, template: DatasheetTemplate) -> dict[str, Any]:
    """Pure function: PDF + template → canonical-payload dict.

    Tested with synthetic text directly via :func:`scrape_text`.
    """
    text = _extract_pdf_text(pdf_path)
    return scrape_text(text, template)


def scrape_text(text: str, template: DatasheetTemplate) -> dict[str, Any]:
    """Same as :func:`scrape_datasheet`, but takes pre-extracted
    text — used by tests so we don't need to render a PDF.
    """
    return {
        "memories": _scrape_memory_map(text, template),
        "peripherals": _scrape_peripherals(text, template),
    }


def _resolve_pdf(request: ExtractionRequest) -> Path | None:
    return request.source_paths.get("datasheet-pdf")


def _resolve_template(request: ExtractionRequest) -> Path | None:
    return request.source_paths.get("datasheet-template")


@register_extractor(
    "datasheet-pdf",
    families=(("__pdf_scrape__", "__pdf_scrape__"),),
)
class DatasheetPdfExtractor:
    """PDF datasheet scraper — Phase 4.1 implementation."""

    extractor_id: str = "datasheet-pdf"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        pdf_path = _resolve_pdf(request)
        template_path = _resolve_template(request)
        if pdf_path is None or template_path is None:
            available = sorted(request.source_paths)
            raise ValueError(
                "datasheet-pdf extractor: requires "
                "--source datasheet-pdf=<path> + "
                "--source datasheet-template=<path>.  "
                f"Got source keys: {available}"
            )
        if not pdf_path.exists():
            raise ValueError(f"datasheet-pdf extractor: PDF not found: {pdf_path}")
        if not template_path.exists():
            raise ValueError(f"datasheet-pdf extractor: template not found: {template_path}")

        template = load_template(template_path, vendor=request.vendor)
        scraped = scrape_datasheet(pdf_path, template)

        payload: dict[str, Any] = {
            "schema_version": "1.3.0",
            "identity": {
                "vendor": request.vendor,
                "family": request.family,
                "device": request.device,
                "core": "",
                "summary": f"PDF-scraped from {pdf_path.name}",
            },
            "provenance": {
                "source_id": "datasheet-pdf-scrape",
                "source_path": str(pdf_path),
                "patch_ids": [f"datasheet-template:{template_path.name}"],
                "confidence": "low",
            },
            "memories": scraped["memories"],
            "peripherals": scraped["peripherals"],
        }
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="datasheet-pdf-scrape",
                source_path=str(pdf_path),
                revision=request.revision,
            ),
            warnings=(
                "datasheet-pdf extractor produces low-confidence "
                "YAMLs — codegen consumers must opt-in via "
                "--accept-low-confidence to load them.",
            ),
        )


__all__ = [
    "DatasheetPdfExtractor",
    "DatasheetTemplate",
    "load_template",
    "scrape_datasheet",
    "scrape_text",
]
