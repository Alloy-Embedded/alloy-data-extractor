"""STM32 extractor — `migrate-stm32-extractor` (Phase 1.1) scaffold.

This module is registered as the canonical extractor for STM32
families (`stm32f4`, `stm32g0` today; the rest as bulk discovery
admits them via Phase 2.1).  The current implementation is a
**deferring stub**: when Phase 1.1's full parser port lands,
this module gains the CMSIS-SVD + STM32_open_pin_data reading
logic ported wholesale from
``alloy-codegen/src/alloy_codegen/sources/cmsis_svd.py`` and
``alloy-codegen/src/alloy_codegen/sources/stm32_open_pin_data.py``.

Until then, calling ``extract()`` raises ``NotImplementedError``
with a clear message pointing at the migration task.  The
registration itself is meaningful because:

* It claims `(st, stm32f4)` and `(st, stm32g0)` in the registry
  ahead of CMSIS-SVD's vendor-wide binding, so the resolver
  picks STM32 specifically once an implementation lands.
* Anyone running ``alloy-data-extract --vendor st --family stm32g0``
  today gets a ``NotImplementedError`` referencing the migration
  rather than a silent fallback to a half-complete CMSIS-SVD
  pass.

See ``ROADMAP.md`` for the full Phase-1 plan and
``PHASE_1_HANDOFF.md`` for the recipe each migration follows.
"""

from __future__ import annotations

from alloy_data_extractor.extractor_protocol import (
    ExtractionRequest,
    ExtractionResult,
    register_extractor,
)


@register_extractor(
    "stm32",
    families=(
        ("st", "stm32f4"),
        ("st", "stm32g0"),
    ),
)
class Stm32Extractor:
    """STM32 extractor — Phase 1.1 scaffold (full port pending)."""

    extractor_id: str = "stm32"

    def supports(self, vendor: str, family: str) -> bool:  # noqa: D401
        del vendor, family
        return False  # decorator-derived bindings handle admission

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "STM32 extractor is not yet implemented — Phase 1.1 "
            "(`migrate-stm32-extractor`) ports the CMSIS-SVD + "
            "STM32_open_pin_data parsers from alloy-codegen.  Until "
            "then, alloy-codegen runs the legacy `_build_st_device_ir` "
            "path directly.  See ROADMAP.md and PHASE_1_HANDOFF.md."
        )


__all__ = ["Stm32Extractor"]
