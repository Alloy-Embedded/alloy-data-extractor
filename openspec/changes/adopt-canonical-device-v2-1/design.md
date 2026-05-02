# Design — adopt-canonical-device-v2-1

## Why this is one OpenSpec, not three

The migration touches three repos but every fork is inter-locked:

* If alloy-codegen alone moves to v2.1 it can't read the v1 YAMLs in
  the submodule.
* If alloy-data-extractor alone emits v2.1 the codegen submodule
  rejects them.
* If alloy-devices-yml alone is re-emitted the extractor can't
  re-validate the round-trip.

Splitting would require a v1↔v2.1 bridge in two places (writer + reader)
that we've explicitly chosen not to ship.  One OpenSpec, one cutover.

## Why drop v1 entirely

* v1 carries 30+ top-level sections; 11 are produced by alloy-codegen
  synthesis (empty in the YAMLs) and would be regenerated identically
  in v2.1 — the storage format is irrelevant to them.
* The remaining 19 sections collapse cleanly to `templates`,
  `peripherals`, `pinout`, `clock`, `memory`, `interrupts` —
  documented + audited in `proposals/canonical-v2-handcrafted/`.
* Carrying both shapes through the merge engine, the IR, the cache,
  the validator, the bulk-admit script, and 14 vendor extractors is
  ~6 000 LOC of fork.  We have no consumer that needs v1 specifically.
* The data is recoverable.  Every v1 YAML in alloy-devices-yml was
  produced from upstream sources (CMSIS-SVD, ATDF, CubeMX, Zephyr DTS,
  Pico SDK, modm-devices, …); re-running the (rewritten) extractor
  pipeline regenerates v2.1 deterministically.

## Cutover sequence

Five phases, each one merge-ready in isolation, but the chain MUST land
together:

1. **Schema in tree** — relocate
   `proposals/canonical-v2-handcrafted/schema/` to
   `schema/canonical_device_v2_1/` in alloy-codegen and alloy-devices-yml
   (the data repo vendors the same JSON file as the codegen does).
2. **New IR + reader/writer** — `alloy_codegen.ir.v2_1.*` +
   `alloy_codegen.canonical_device_v2_1` land alongside the legacy
   modules, gated behind `if CANONICAL_SCHEMA_DEFAULT == "v2.1"`.
3. **Extractor rewrite** — every per-vendor extractor stops emitting
   v1 primitive shape and emits v2.1 directly.  `merge.py` rewires.
4. **Soak window** — for one CI cycle, both pipelines run in parallel.
   The v2.1 emitter writes to `proposals/canonical-v2-handcrafted-bulk/`;
   reviewers cross-check it against the v1 corpus.  No production
   change yet.
5. **Cutover** — alloy-devices-yml content replaced atomically.
   alloy-codegen's data submodule pin moved.  The legacy modules
   (`ir/model.py`, `canonical_device_yaml.py`, `emit/canonical_yaml.py`)
   are deleted in the same commit.  Tests + goldens regenerated.

## IR module layout (alloy-codegen)

```
src/alloy_codegen/
├── ir/
│   ├── __init__.py            ← re-exports the v2_1 IR as the public surface
│   ├── v2_1/
│   │   ├── __init__.py
│   │   ├── identity.py        ← Identity, Core, Multicore
│   │   ├── memory.py          ← MemoryRegion + AddressSpace enum
│   │   ├── clock.py           ← Oscillator, PLLConfig, ClockDomain,
│   │   │                        ClockProfile, SelectRegister
│   │   ├── templates.py       ← Template, TemplateRegister, TemplateField,
│   │   │                        FieldEnum, TimerExtras (trigger/master/deadtime)
│   │   ├── peripherals.py     ← PeripheralInstance, PeripheralIRQ,
│   │   │                        PeripheralDMA, PinOptions, AdcCalibration,
│   │   │                        ExternalTrigger, I2cTimingPreset
│   │   ├── pinout.py          ← Pin, PinConstraint enum
│   │   ├── interrupts.py      ← VectorTable | InterruptMatrix
│   │   └── device.py          ← CanonicalDevice (top-level aggregate)
│   └── synthesised/           ← in-memory only; never serialised
│       ├── route_operations.py
│       ├── route_requirements.py
│       ├── connection_candidates.py
│       ├── connection_groups.py
│       ├── interrupt_bindings.py
│       └── vector_slots.py
├── canonical_device_v2_1.py   ← parse_device / serialize_device / validate_device
├── connector_model.py         ← rewritten to read v2_1 IR + emit synthesised rows
├── runtime_lite_emission.py   ← rewritten for templates.<ip>.fields lookup
├── emission.py                ← same
└── validation.py              ← same
```

## Extractor rewrite plan (alloy-data-extractor)

Each per-vendor module stops returning a `payload: dict` in the v1
shape and instead returns a typed `V21Payload` dataclass that mirrors
the v2.1 schema 1:1:

```python
@dataclass(slots=True)
class V21Payload:
    schema:        str = "alloy.device.v2.1"
    identity:      Identity
    provenance:    Provenance
    memory:        list[MemoryRegion]
    clock:         Clock
    templates:     dict[str, Template]
    peripherals:   list[PeripheralInstance]
    pinout:        list[Pin]
    interrupts:    list[IrqEntry] | InterruptMatrix
    fuses:         dict | None = None
    system_examples: dict | None = None
```

The merge engine still composes a primary + N enrichments — but the
field-priority paths now live in the v2.1 namespace
(`templates.<ip>.fields`, `peripherals[].rcc`, etc.).  The
STM32-specific extension fields (`adc.calibration`,
`i2c.timing_presets`) become first-class methods on the merger.

Per-vendor extractor effort estimate:

| Module                          | Effort            |
|---------------------------------|-------------------|
| `cmsis_svd.py`                  | rewrite (large)   |
| `stm32.py`                      | rewrite (large)   |
| `stm32_cubemx.py`               | rewrite (medium)  |
| `stm32_tier.py`                 | refactor (small)  |
| `stm32_overlay.py`              | rewrite (medium)  |
| `microchip_atdf.py`             | rewrite (large)   |
| `nordic_zephyr_dts.py`          | rewrite (medium)  |
| `espressif_*` (3 modules)       | rewrite (large)   |
| `nxp_imxrt.py`                  | rewrite (medium)  |
| `raspberrypi_pico_sdk.py`       | rewrite (medium)  |
| `modm_devices.py`               | rewrite (medium)  |
| `pic.py`, `msp430.py`, `8051.py`| rewrite (small)   |

Total: ~14 modules, ~6 000 LOC of pipeline + ~2 000 LOC of tests.

## Schema-locked emission

The validator from
`proposals/canonical-v2-handcrafted/schema/validate.py` becomes a hard
gate in three places:

1. `emit/canonical_yaml_v2_1.write_device_yaml(payload)` —
   pre-validates before `yaml.dump`, raises `StageExecutionError` on
   schema drift.
2. CI workflow `validate-v21` in alloy-devices-yml — every PR touching
   `vendors/**/devices/*.yml` runs the validator.
3. alloy-codegen test `test_canonical_device_v2_1.py` — round-trips
   every admitted YAML through `parse_device(serialize_device(parse_device(text)))`
   and asserts byte-equal output.

## What stops working during the soak

* `alloy-codegen` cannot emit C++ for any chip during the soak — both
  pipelines are present, but the consumer is gated to v1 only.  This
  is the entire reason the soak is just one CI cycle: nobody runs
  builds for affected chips during the window.
* The CI integration tests skip during the soak; they re-enable in the
  cutover commit with refreshed goldens.

## What stays unchanged

* The merge engine's three-way priority semantics (primary + N
  enrichments, per-field source priorities) — only the path namespace
  shifts to v2.1.
* The binary IR cache (Phase 3 of the previous OpenSpec) — only the
  cache key bumps from `IR_SCHEMA_VERSION` to `CANONICAL_SCHEMA`.
* The vendor admission flow — chips still go through draft → reviewed
  → admitted; only the YAML format at the end of the funnel changes.
* The submodule layout — `data/devices/vendors/<v>/<f>/devices/<d>.yml`
  stays as-is.

## Risks + mitigations

| Risk                                                | Mitigation                                                  |
|-----------------------------------------------------|-------------------------------------------------------------|
| Re-emit drops a fact codegen needs                  | Audit doc + the 13 deltas; soak parallel-runs both          |
| A vendor extractor regresses                         | Per-vendor pytest goldens; merge gates on green             |
| Submodule pin races between codegen + data-yml      | One PR moves the pin AND ships the codegen rewrite          |
| Soak window unexpectedly long                        | Soak gated behind a CI label; revertable by reverting one   |
|                                                     | submodule pin                                                |
| Schema validator too strict on real-world YAMLs     | 7 negative tests pin the rules; loosen by adding additional |
|                                                     | positive cases first                                         |

## Why no v1↔v2.1 bridge

* The data is reproducible from upstream sources — bridge would let us
  defer the rewrite, but the rewrite is the value.
* A bridge implies both shapes survive in production indefinitely; the
  pull to maintain them grows linearly with admitted chips.
* Reviewers reading either shape would have to learn both.
* Storage cost of a bridge (the v1 schema, the IR dataclasses, the
  reader, the writer) is roughly equal to one of the per-vendor
  extractors we're rewriting.

## After this OpenSpec

* `OpenSpec compact-canonical-yaml-and-cache-loads` archive becomes
  partially obsolete — Phase 2's `provenance_defaults` mechanism is
  not needed in v2.1 (no per-row provenance).  The Phase 3 binary IR
  cache survives, just keyed on the new schema constant.
* A follow-up OpenSpec `cross-vendor-template-namespace` formalises
  template ids like `usart-stm32-v1`, `uart-primecell-pl011`,
  `uarte-nordic-v1` so codegen's emitter dispatches by IP-version
  instead of by chip name.
