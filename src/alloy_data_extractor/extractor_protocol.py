"""The single Protocol every extractor in this package implements.

`define-extractor-protocol` (Phase 0.2 of the roadmap) replaces
the ad-hoc per-module entry points with one uniform interface so
the pipeline dispatches generically — no per-vendor `if`
cascades, no source-format-specific positional parameters.

Public surface:

* :class:`Extractor` — the Protocol every extractor implements.
* :class:`ExtractionRequest` — uniform input.
* :class:`ExtractionResult` — uniform output.
* :class:`ProvenanceRecord` — provenance shape.
* :func:`register_extractor` — decorator wiring an extractor
  into the registry.
* :func:`resolve_extractor` — looks up an extractor by
  `(vendor, family)`.
* :func:`resolve_extractor_by_id` — looks up by id.
* :func:`registered_extractor_ids` — for CLI discovery.

Concrete extractors (cmsis_svd, zephyr_dts, …) register
themselves at import time via :func:`register_extractor`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class MissingSourceError(KeyError):
    """Raised when an extractor needs a source path that the
    request did not supply.  Subclass of KeyError so callers can
    catch it with the same idiom as a missing-dict-key.
    """


class ExtractorRegistrationError(ValueError):
    """Raised when two extractors try to claim the same id, or
    when the extractor decorator gets bad arguments.
    """


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Captures *where* a payload came from.

    Attached to every :class:`ExtractionResult`; flows into
    `vendors/<v>/<f>/devices/<d>.yml`'s ``provenance`` field so
    reviewers can trace any byte back to its upstream source.
    """

    source_id: str
    source_path: str | None
    revision: str
    extracted_at: str = field(
        default_factory=lambda: datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    patch_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """Uniform input shape for every extractor.

    `source_paths` is keyed by source-id (e.g. ``"cmsis-svd"``,
    ``"zephyr-dts"``, ``"stm32cubemx-db"``) so the extractor
    looks up exactly the source it needs by name rather than
    relying on positional params.
    """

    vendor: str
    family: str
    device: str
    source_paths: dict[str, Path]
    revision: str
    extra: dict[str, Any] = field(default_factory=dict)

    def require_source(self, key: str) -> Path:
        """Look up ``source_paths[key]`` or raise
        :class:`MissingSourceError` with a discoverable message.
        """
        if key not in self.source_paths:
            raise MissingSourceError(
                f"extractor needs source path keyed {key!r}, but the "
                f"request only supplied: {sorted(self.source_paths)}"
            )
        return self.source_paths[key]


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Uniform output shape for every extractor."""

    payload: dict[str, Any]
    provenance: ProvenanceRecord
    warnings: tuple[str, ...] = ()


@runtime_checkable
class Extractor(Protocol):
    """The contract every concrete extractor implements.

    An extractor declares which `(vendor, family)` pairs it
    serves, then resolves an :class:`ExtractionRequest` into an
    :class:`ExtractionResult` carrying canonical-YAML-shaped
    payload + provenance.
    """

    extractor_id: str

    def supports(self, vendor: str, family: str) -> bool:
        """Return True if this extractor admits ``(vendor, family)``."""
        ...

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Run extraction.  Raises :class:`MissingSourceError`
        when a required source path is not in the request.
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, Extractor] = {}


def register_extractor(
    extractor_id: str,
    *,
    vendors: Iterable[str] = (),
    families: Iterable[tuple[str, str]] = (),
):
    """Decorator wiring an :class:`Extractor` into the registry.

    Two binding modes:

    * ``vendors=("st",)`` — admits every family of the listed vendors.
    * ``families=(("st", "stm32g0"), ("st", "stm32f4"))`` — admits
      explicit `(vendor, family)` pairs.

    Use ``vendors`` for source-format adapters that admit any
    chip a vendor publishes (CMSIS-SVD covers many vendors via
    the same XML format); use ``families`` for adapters that
    are family-specific.
    """
    vendors_tuple = tuple(vendors)
    families_tuple = tuple(families)
    if not vendors_tuple and not families_tuple:
        raise ExtractorRegistrationError(
            f"register_extractor({extractor_id!r}): must declare at least one of "
            "`vendors=` or `families=`."
        )

    def decorator(cls_or_factory):
        instance: Extractor
        if isinstance(cls_or_factory, type):
            instance = cls_or_factory()
        else:
            instance = cls_or_factory  # already an instance / factory output
        if not isinstance(instance, Extractor):
            raise ExtractorRegistrationError(
                f"register_extractor({extractor_id!r}): registered object does not "
                f"satisfy the Extractor protocol ({type(instance).__name__})."
            )
        # Stamp the id and the supports() lookup tables.
        object.__setattr__(instance, "extractor_id", extractor_id)
        object.__setattr__(instance, "_admitted_vendors", frozenset(vendors_tuple))
        object.__setattr__(
            instance, "_admitted_families", frozenset(families_tuple)
        )
        if extractor_id in _REGISTRY:
            raise ExtractorRegistrationError(
                f"extractor id {extractor_id!r} is already registered "
                f"by {type(_REGISTRY[extractor_id]).__name__}."
            )
        _REGISTRY[extractor_id] = instance
        return cls_or_factory

    return decorator


def _admits(extractor: Extractor, vendor: str, family: str) -> bool:
    """Default supports() implementation reading the registry's
    bindings.  An extractor that overrides ``supports()`` wins."""
    if extractor.supports(vendor, family) is True:
        return True
    vendors = getattr(extractor, "_admitted_vendors", frozenset())
    families = getattr(extractor, "_admitted_families", frozenset())
    if vendor in vendors:
        return True
    if (vendor, family) in families:
        return True
    return False


def _is_family_specific(extractor: Extractor, vendor: str, family: str) -> bool:
    """True if the extractor admits this pair via its
    family-binding (more specific) rather than a vendor-wide
    catch-all.
    """
    return (vendor, family) in getattr(extractor, "_admitted_families", frozenset())


def resolve_extractor(vendor: str, family: str) -> Extractor:
    """Return the extractor admitting ``(vendor, family)``.

    Specificity rule: when a family-bound extractor and a
    vendor-wide extractor both admit the pair, the family-bound
    one wins.  This lets vendor-specific extractors (e.g.
    ``stm32``) take over for the ST families while CMSIS-SVD
    stays the catch-all for the rest.

    Raises :class:`ValueError` if no extractor admits the pair
    or if multiple equally-specific candidates do.
    """
    candidates = [ext for ext in _REGISTRY.values() if _admits(ext, vendor, family)]
    if not candidates:
        raise ValueError(
            f"no extractor registered for ({vendor!r}, {family!r}). "
            f"Registered: {_format_bindings()}"
        )
    # Specificity tier: family-bound > vendor-bound.
    family_specific = [c for c in candidates if _is_family_specific(c, vendor, family)]
    if family_specific:
        if len(family_specific) == 1:
            return family_specific[0]
        ids = sorted(c.extractor_id for c in family_specific)
        raise ValueError(
            f"ambiguous: {len(family_specific)} family-specific extractors admit "
            f"({vendor!r}, {family!r}): {ids}.  Pick one via resolve_extractor_by_id(...)."
        )
    if len(candidates) == 1:
        return candidates[0]
    ids = sorted(c.extractor_id for c in candidates)
    raise ValueError(
        f"ambiguous: {len(candidates)} extractors admit ({vendor!r}, {family!r}): "
        f"{ids}.  Pick one explicitly via resolve_extractor_by_id(...)."
    )


def resolve_extractor_by_id(extractor_id: str) -> Extractor:
    """Return the extractor with the given id, or raise."""
    if extractor_id not in _REGISTRY:
        # Keep the legacy error wording so callers checking
        # `match="unknown extractor_id"` continue to match.
        raise ValueError(
            f"unknown extractor_id {extractor_id!r}; "
            f"known: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[extractor_id]


def registered_extractor_ids() -> tuple[str, ...]:
    """Return every registered extractor id, sorted."""
    return tuple(sorted(_REGISTRY))


def _format_bindings() -> str:
    """Pretty-print the registry for error messages."""
    lines: list[str] = []
    for ext_id in sorted(_REGISTRY):
        ext = _REGISTRY[ext_id]
        vendors = sorted(getattr(ext, "_admitted_vendors", set()))
        families = sorted(getattr(ext, "_admitted_families", set()))
        descriptors = []
        if vendors:
            descriptors.append(f"vendors={vendors}")
        if families:
            descriptors.append(f"families={families}")
        lines.append(f"  {ext_id}: {', '.join(descriptors)}")
    return "\n" + "\n".join(lines) if lines else "<empty>"


def _reset_registry_for_tests() -> None:
    """Clear the registry between tests.  Tests that register
    synthetic extractors call this in tearDown to avoid leaks."""
    _REGISTRY.clear()


__all__ = [
    "Extractor",
    "ExtractionRequest",
    "ExtractionResult",
    "ExtractorRegistrationError",
    "MissingSourceError",
    "ProvenanceRecord",
    "register_extractor",
    "registered_extractor_ids",
    "resolve_extractor",
    "resolve_extractor_by_id",
]
