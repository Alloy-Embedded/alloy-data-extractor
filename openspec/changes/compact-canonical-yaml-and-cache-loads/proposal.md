# Compact Canonical YAML + Cache IR Loads

## Why

Two adjacent problems block the path to 5 000+ admitted MCUs:

1. **Canonical YAMLs carry ~30 % bloat the codegen never reads.**
   A field-by-field audit of every consumer in `alloy-codegen`
   (`runtime_lite_emission`, `emission`, `validation`,
   `connector_model`, `runtime_*`) confirms that:

   - `RegisterFieldDescriptor.provenance` is *never* read.
   - `RouteOperation.{target, value, register_peripheral,
     register_name, register_offset}` are pure diagnostic echoes
     resolved from the typed `register_id` / `register_field_id`
     refs — validation only checks nullability, the values are
     never consumed.
   - `RouteRequirement.{target, value}` are similarly diagnostic
     echoes.
   - `ClockGate` / `Reset` row’s `register_peripheral`,
     `register_name`, `register_offset` already have
     `omit_if_empty` metadata but the extractors keep emitting
     them with values; same diagnostic pattern.
   - `VectorSlotDescriptor.core_affinity` defaults to `"cpu0"`
     and is never read by emitters.
   - Per-row `provenance` blocks (which dominate the file —
     ~30 % of an STM32 YAML) are read **only** by
     `runtime_reports.py` for audit/explainability output.  The
     emitted C++ never depends on them.

   On `stm32g0b1re.yml` (108 676 bytes, 4 241 lines):

   | Tier | Saving |
   |---|---|
   | A — drop never-read fields | ~11 % |
   | A + hoist provenance to top-level default | **~35 %** |

2. **YAML parse + dataclass instantiation dominates load time.**
   Measured per-chip cold load (`parse_device(text)`):

   | Chip | YAML+dataclass | Pickle | Speedup |
   |---|---|---|---|
   | stm32g0b1re | 33 ms | 1.4 ms | **23×** |
   | esp32s3 | 1 994 ms | 70 ms | **28×** |
   | atsame70q21b | **3 286 ms** | 108 ms | **30×** |

   For 5 000 chips: a full bulk-admit pass spends 4.6 hours on
   load alone with the SAM70-class fanout.  With a cached
   pickle of the parsed IR, that drops to ~9 minutes.

The current OpenSpec bundles three independent improvements
that compose for a combined ~35 % YAML shrink + ~25–50× faster
loads on the codegen side, with one schema bump (1.5.0,
additive).

## What Changes

### Phase 1 — Drop never-read fields *(no schema bump)*

Mark the 11 confirmed-never-read fields as
`omit_if_empty` in the IR dataclass, and stop populating them
in every `alloy_data_extractor` extractor that currently does.
Existing payloads that still carry the values continue to load
because the IR keeps the field as `Optional` with a default.

Affected dataclasses in `alloy_codegen.ir.model`:

- `RouteOperation` — convert `target: str` to `str | None`,
  add `omit_if_empty` to `target`, `value`,
  `register_peripheral`, `register_name`, `register_offset`,
  `subject_kind`, `subject_id`.
- `RouteRequirement` — add `omit_if_empty` to `target`,
  `value`.
- `RegisterFieldDescriptor` — `provenance` becomes
  `Provenance | None` with `omit_if_empty`; the field’s
  audit metadata is reconstructed from the top-level
  provenance + field-id at read time when missing.

Net YAML reduction on the ST corpus: ~11 %, no schema bump
(payloads are valid 1.4.0 documents).

### Phase 2 — Provenance audit sidecar *(schema 1.5.0)*

Per-row `provenance` blocks move from the canonical YAML to a
sibling **audit sidecar** at
`vendors/<v>/<f>/devices/<d>.audit.yml`.

- Canonical YAML keeps the **top-level** `provenance`
  (identity + source bundle).
- Sidecar holds the per-row mapping
  `{<row_id>: Provenance, ...}`.
- `parse_device(text, audit_sidecar=...)` overlays the audit
  payload back onto the IR so the dataclass tree is identical
  to the pre-1.5.0 shape.  When the sidecar is absent the
  parser synthesises each row’s provenance from the top-level
  default — codegen still runs because *no emitter reads
  per-row provenance*; only `runtime_reports.py` cares, and
  it learns to ask for the sidecar explicitly.
- `serialize_device(ir)` learns to emit
  `(canonical_text, audit_text)` so the data-extractor pipeline
  writes both files in lockstep.

Schema bump: **1.4.0 → 1.5.0**.  Additive: `provenance` on
each row is now optional; new top-level field
`provenance_audit_path` (relative path string) declared but
not required.

### Phase 3 — Binary IR cache *(codegen-side)*

Add `.cache/canonical_ir/<vendor>/<family>/<device>.<sha8>.pkl`
populated by `load_canonical_device` after the first
successful parse.  Subsequent loads:

1. Hash the YAML text → `sha = sha256(text)[:16]`.
2. If `cache.<sha>.pkl` exists, `pickle.loads` it (≤ 100 ms
   even for SAM70-class) and return.
3. Else fall through to the regular YAML parse path and write
   the cache atomically (`pickle.dumps(ir, protocol=5)` →
   `os.replace`).

Cache directory:

- Per-process default: alongside the YAMLs in
  `<repo>/.cache/canonical_ir/`.
- Configurable via `ALLOY_CODEGEN_IR_CACHE_DIR`
  environment variable.
- Cache disable knob: `ALLOY_CODEGEN_IR_CACHE=0` for
  CI runs that need byte-deterministic re-parsing.
- `.gitignore` add: `.cache/canonical_ir/`.

The cache key incorporates `(IR_SCHEMA_VERSION,
sha256(yaml_text))` so codegen schema bumps automatically
invalidate every cached entry.

## Impact

- **alloy-codegen** ⟶ `ir/model.py`,
  `canonical_device_yaml.py`, `serialization.py`,
  `sources/alloy_devices_yml.py`, `runtime_reports.py`,
  schema files `schema/canonical_device/*.json`.
- **alloy-data-extractor** ⟶ extractors that emit the
  removed fields stop populating them; new
  `audit_sidecar.py` helper writes the per-row provenance
  payload; pipeline writes both files.
- **alloy-devices-yml** ⟶ every admitted YAML re-emitted
  under schema 1.5.0; new `<device>.audit.yml` sidecar
  shipped.  Submodule contents shrink ~35 % on average.

Backwards compatibility:

- alloy-codegen accepts schema 1.4.0 *and* 1.5.0 YAMLs.
  1.4.0 payloads continue to carry per-row provenance
  inline; the parser uses it directly.
- 1.5.0 payloads without an audit sidecar load successfully
  (provenance for each row falls back to the top-level
  bundle’s identity).  `runtime_reports.py` reports
  `audit-sidecar-missing` for any row whose sidecar entry
  is absent.
