"""STM32 family-overlay extractor — `complete-stm32-tier-coverage`
Phase 5.

Reads `data/vendors/st/<family>/family.toml` (and the optional
`data/vendors/st/<family>/devices/<device>.toml` per-chip
override) carrying the truly hand-curated tier-2/3/4 constants
that no upstream source structures uniformly:

* RM-table values (max_clock_hz across peripheral classes).
* Calibration ROM addresses (per-family uniform; per-chip
  overrides only when ST relocates them).
* Internal ADC channel assignments (vrefint / temperature_sensor
  / vbat → channel index — per-family fact).
* Default system-clock profiles (post-reset state and
  recommended PLL configs).
* I2C speed_options (universal 3 modes with optional family
  cap).

Phase 4 of the OpenSpec was originally scoped to derive the
calibration ROM addresses from CMSIS device headers
(`stm32g071xx.h::TEMPSENSOR_CAL1_ADDR`).  Those headers aren't
locally staged on this workstation, so the family TOMLs absorb
that data instead — adding a CMSIS-headers extractor as a
follow-up automation can replace these entries deterministically
when the headers are staged.

This extractor is **secondary**: the merge engine
(`STM32_MERGE_POLICY`) folds its output onto a primary STM32
extraction.  Per-row provenance carries
``source_id="stm32-overlay"`` plus the TOML's relative path so
reviewers can trace which TOML supplied each datum.
"""

from __future__ import annotations

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
from alloy_data_extractor.extractors.stm32_i2c_timing import (
    compute_i2c_timing_presets_for_speeds_and_clocks,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_OVERLAY_ROOT = _REPO_ROOT / "data" / "vendors" / "st"


@dataclass(frozen=True, slots=True)
class _LoadedOverlay:
    """One layer of overlay data with its source-path tag."""

    relative_path: str
    data: dict[str, Any]


def _load_toml(path: Path) -> _LoadedOverlay | None:
    if not path.exists():
        return None
    with path.open("rb") as fp:
        data = tomllib.load(fp)
    # When the path lives under the repo root, render the relative
    # form so provenance is environment-stable; otherwise fall back
    # to the path's name (for tests / out-of-tree overlays).
    try:
        relative = str(path.relative_to(_REPO_ROOT))
    except ValueError:
        relative = path.name
    return _LoadedOverlay(relative_path=relative, data=data)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Per-device override wins over family defaults.  Lists
    inside override REPLACE the base list — they never append —
    so the per-device file can declare e.g. a different
    calibration_data_points roster without keeping the family's.
    """
    out = dict(base)
    for key, value in override.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _stamp_provenance(
    rows: list[dict[str, Any]],
    *,
    source_path: str,
    revision: str,
) -> list[dict[str, Any]]:
    """Stamp per-row provenance.  Mutates each row's dict to add
    ``provenance``.  Lists of bare values (e.g. just numbers)
    are skipped — only dicts gain provenance."""
    stamped: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            stamped.append(row)
            continue
        with_prov = dict(row)
        with_prov["provenance"] = {
            "source_id": "stm32-overlay",
            "source_path": source_path,
            "patch_ids": (
                [f"stm32-overlay@{revision}"] if revision else ["stm32-overlay"]
            ),
        }
        stamped.append(with_prov)
    return stamped


def _project_overlay(
    overlay_data: dict[str, Any],
    *,
    source_path: str,
    revision: str,
) -> dict[str, Any]:
    """Project the merged overlay TOML into canonical-IR-shaped
    payload fields.  Return value is a mapping of canonical
    field-name to its row set."""
    payload: dict[str, Any] = {}

    adc = overlay_data.get("adc") or {}
    if "max_clock_hz" in adc:
        payload["adc_max_clock_hz"] = adc["max_clock_hz"]
    if "calibration_context" in adc:
        payload["adc_calibration_context"] = {
            **adc["calibration_context"],
            "provenance": {
                "source_id": "stm32-overlay",
                "source_path": source_path,
                "patch_ids": (
                    [f"stm32-overlay@{revision}"]
                    if revision
                    else ["stm32-overlay"]
                ),
            },
        }
    if "calibration_data_points" in adc:
        payload["adc_calibration_data_points"] = _stamp_provenance(
            list(adc["calibration_data_points"]),
            source_path=source_path,
            revision=revision,
        )
    if "internal_channels" in adc:
        payload["adc_internal_channels"] = _stamp_provenance(
            list(adc["internal_channels"]),
            source_path=source_path,
            revision=revision,
        )

    uart = overlay_data.get("uart") or {}
    if "max_baud_hz" in uart:
        payload["uart_max_baud_hz"] = uart["max_baud_hz"]

    i2c = overlay_data.get("i2c") or {}
    if "max_clock_hz" in i2c:
        payload["i2c_max_clock_hz"] = i2c["max_clock_hz"]
    # `i2c_speed_options` per-instance is owned by stm32-tier (which
    # has access to the CubeMX peripheral list).  The overlay
    # carries the family-level speed list for the I2C-timing
    # cross-product computation but doesn't emit speed_options
    # rows itself anymore.

    system_clock = overlay_data.get("system_clock") or {}
    profiles: list[dict[str, Any]] = []
    if "post_reset_profile" in system_clock:
        post_reset = dict(system_clock["post_reset_profile"])
        # Canonical SystemClockProfile shape requires profile_id +
        # source_kind alongside kind / sysclk_hz.
        post_reset.setdefault("profile_id", post_reset.get("name", "post-reset"))
        post_reset["kind"] = "post-reset"
        post_reset["source_kind"] = post_reset.get("source", "unknown")
        profiles.append(post_reset)
    for recommended in system_clock.get("recommended_profiles", []) or []:
        row = dict(recommended)
        row.setdefault("profile_id", row.get("name", "recommended"))
        row["kind"] = "recommended"
        row["source_kind"] = row.get("source", "unknown")
        profiles.append(row)
    if profiles:
        payload["system_clock_profiles"] = _stamp_provenance(
            profiles, source_path=source_path, revision=revision
        )

    # Phase 6 — i2c_timing_presets computed from the (peripheral
    # × speeds × sysclk profiles) cross product when all three
    # inputs are available.  The overlay reads the per-chip I2C
    # instance list from the merge engine's primary payload via
    # the helper-attached `_overlay_instances` parameter (passed
    # in by the extractor's `extract` method when CubeMX is
    # staged).  Without instance info, the timing presets aren't
    # emitted (the merge engine then accepts the empty default).
    return payload


def _resolve_overlay(
    *, family: str, device: str, overlay_root: Path = _OVERLAY_ROOT
) -> tuple[dict[str, Any], list[str]]:
    """Resolve the merged overlay for ``family`` + ``device``.
    Returns ``(merged_data, source_paths)`` — the source-paths
    list captures every TOML that contributed (family + per-device
    override) for provenance auditing.
    """
    family_path = overlay_root / family / "family.toml"
    device_path = overlay_root / family / "devices" / f"{device}.toml"

    family_overlay = _load_toml(family_path)
    device_overlay = _load_toml(device_path)

    if family_overlay is None and device_overlay is None:
        return {}, []

    merged: dict[str, Any] = {}
    paths: list[str] = []
    if family_overlay is not None:
        merged = _deep_merge(merged, family_overlay.data)
        paths.append(family_overlay.relative_path)
    if device_overlay is not None:
        merged = _deep_merge(merged, device_overlay.data)
        paths.append(device_overlay.relative_path)
    return merged, paths


@register_extractor(
    "stm32-overlay",
    families=(("__stm32_overlay_secondary__", "__stm32_overlay_secondary__"),),
)
class Stm32OverlayExtractor:
    """STM32 family-overlay secondary EnrichmentExtractor."""

    extractor_id: str = "stm32-overlay"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        # Allow callers to point at a different overlay root via
        # `--source stm32-overlay-root=<path>` for tests.
        overlay_root = request.source_paths.get("stm32-overlay-root", _OVERLAY_ROOT)
        merged_data, source_paths = _resolve_overlay(
            family=request.family,
            device=request.device,
            overlay_root=overlay_root,
        )

        if not merged_data:
            return ExtractionResult(
                payload={
                    "schema_version": "1.4.0",
                    "identity": {
                        "vendor": request.vendor,
                        "family": request.family,
                        "device": request.device,
                        "core": "",
                    },
                    "provenance": {
                        "source_id": "stm32-overlay",
                        "source_path": None,
                        "patch_ids": [],
                    },
                },
                provenance=ProvenanceRecord(
                    source_id="stm32-overlay",
                    source_path=None,
                    revision=request.revision,
                ),
                warnings=(
                    f"stm32-overlay: no TOML at "
                    f"{overlay_root}/{request.family}/family.toml — "
                    "tier-2 constants for this chip will fall through "
                    "the merge to whichever source provides them.",
                ),
            )

        # Provenance source_path lists every TOML that contributed.
        primary_path = source_paths[0] if source_paths else "stm32-overlay"
        projected = _project_overlay(
            merged_data, source_path=primary_path, revision=request.revision
        )

        # Phase 6 — i2c_timing_presets per-instance.  Reads CubeMX
        # MCU XML when `stm32cubemx-db` is staged so we can fan
        # out timing presets per real I2C instance (canonical
        # I2cTimingPresetPatch shape: peripheral / speed_hz /
        # source_clock_hz / timingr_value).
        i2c_speeds = [opt["speed_hz"] for opt in merged_data.get("i2c", {}).get("speed_options", [])]
        sysclk_profiles = projected.get("system_clock_profiles", [])
        sysclk_freqs = sorted({p["sysclk_hz"] for p in sysclk_profiles}) if sysclk_profiles else []
        i2c_instances: list[str] = []
        if "stm32cubemx-db" in request.source_paths:
            try:
                from alloy_data_extractor.extractors.stm32_cubemx import (
                    _find_db_root,
                    _match_mcu_xml,
                    _parse_mcu_xml,
                )

                supplied = request.source_paths["stm32cubemx-db"]
                roots = _find_db_root(supplied)
                if roots is not None:
                    mcu_root, _ = roots
                    mcu_xml = _match_mcu_xml(mcu_root, request.device)
                    if mcu_xml is not None:
                        facts = _parse_mcu_xml(mcu_xml)
                        i2c_instances = [
                            p.instance_name
                            for p in facts.peripheral_instances
                            if p.ip_name == "I2C"
                        ]
            except Exception:  # noqa: BLE001
                pass

        if i2c_instances and i2c_speeds and sysclk_freqs:
            timing_presets = compute_i2c_timing_presets_for_speeds_and_clocks(
                speeds_hz=i2c_speeds, source_clocks_hz=sysclk_freqs
            )
            projected["i2c_timing_presets"] = _stamp_provenance(
                [
                    {
                        "peripheral": instance,
                        "speed_hz": preset.speed_hz,
                        "source_clock_hz": preset.source_clock_hz,
                        "timingr_value": preset.timingr_value,
                    }
                    for instance in sorted(i2c_instances)
                    for preset in timing_presets
                ],
                source_path=primary_path,
                revision=request.revision,
            )

        payload: dict[str, Any] = {
            "schema_version": "1.4.0",
            "identity": {
                "vendor": request.vendor,
                "family": request.family,
                "device": request.device,
                "core": "",
            },
            "provenance": {
                "source_id": "stm32-overlay",
                "source_path": primary_path,
                "patch_ids": (
                    [f"stm32-overlay@{request.revision}"]
                    if request.revision
                    else ["stm32-overlay"]
                ),
                "overlay_layers": list(source_paths),
            },
            **projected,
        }

        warnings: list[str] = []
        if "stm32-overlay" not in payload["provenance"]["patch_ids"][0]:
            pass  # provenance well-formed
        return ExtractionResult(
            payload=payload,
            provenance=ProvenanceRecord(
                source_id="stm32-overlay",
                source_path=primary_path,
                revision=request.revision,
            ),
            warnings=tuple(warnings),
        )


__all__ = [
    "Stm32OverlayExtractor",
    "_project_overlay",
    "_resolve_overlay",
]
