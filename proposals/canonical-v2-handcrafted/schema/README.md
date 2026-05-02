# `alloy.device.v2.1` schema + validator

## Files

```
schema/
├── alloy-device-v2_1.schema.json   ← JSON-schema, Draft 2020-12
├── validate.py                      ← Python CLI validator
├── negative-tests/                  ← 7 deliberately-broken YAMLs
└── README.md                        ← this file
```

## Quick run

```bash
# Validate the 5 hand-crafted reference YAMLs.
python3 schema/validate.py .

# Validate every YAML under a directory (recurses into *.yml + *.yaml).
python3 schema/validate.py /path/to/alloy-devices-yml/vendors

# Single file.
python3 schema/validate.py path/to/chip.yml

# Cap reported errors per file (default 20).
python3 schema/validate.py . --max-errors 5

# Show only failing files.
python3 schema/validate.py . -q
```

Exit codes:

| Code | Meaning                                    |
|------|--------------------------------------------|
| 0    | All inputs validated cleanly                |
| 1    | One or more inputs failed                   |
| 2    | Invocation error (missing arg, bad schema) |

## What the schema enforces

### Top-level required keys

`schema`, `identity`, `provenance`, `memory`, `clock`, `peripherals`,
`pinout`.  `templates`, `interrupts`, `fuses`, `system_examples` are
optional.  Anything else passes through (`additionalProperties: true`)
so vendors can extend without breaking the schema.

### Unit literals

Frequencies must end in `Hz` / `kHz` / `MHz` / `GHz`; sizes in
`B` / `KB` / `MB` / `GB`.  Decimal fractions allowed:
`32.768kHz`, `1.5MHz`, `2MB`.  Plain integers fail validation.

### Hex addresses

Memory base addresses, register offsets, ROM-address calibration
constants, etc. accept either a positive integer **or** a
`0x`-prefixed hex string (`0x08000000`).

### Pin constraints (closed enum)

The 18 pin-constraint tags from the v2.1 audit are pinned to a closed
enum so a typo (`analog_only` vs `analog-only`) trips immediately:

```
analog-only • analog-capable • analog • strapping • flash-reserved
nfc-default • lfxo-bond • input-only • rtc • reset • debug-default
boot • oscillator • power • power-control • chip-enable
module-reserved • low-drive
```

Need a new tag?  Add it to `$defs.pin.properties.constraints.items.enum`.

### Memory access (closed enum)

`r`, `rw`, `rwx`, `rx`, `ro`, `wo`.  Anything else (`rwxv`,
`read-write`, etc.) fails.

### Template fields require a bit position

A `templates.<ip>.fields.<reg>.<name>` entry must declare **exactly
one** of `bit` (single 0-63 integer) or `bits` (two-element range).
Missing both is a hard error — a half-populated extractor row never
silently lands.

### Clock domains require a source

A `clock.domains[]` entry must declare `source: <id>` (single) or
`sources: [<id>, …]` (multiple).  Missing both fails — codegen would
have nothing to write to the SRC field otherwise.

### `select_register` / `select_task` shape

When a domain declares a `select_register`, all three of `reg`,
`field`, `encoding` are required and the encoding must be a non-empty
mapping of `name → integer`.  This catches half-baked mux records the
extractors sometimes emit when their upstream loses a column.

## Demonstrated drift coverage

The seven `negative-tests/*.yml` examples each assert a specific class
of breakage.  Run the validator against them — every one fails:

| File                                          | Catches                                |
|-----------------------------------------------|----------------------------------------|
| `01-wrong-schema-version.yml`                 | wrong `schema:` const                   |
| `02-missing-required-section.yml`             | omitted top-level required key          |
| `03-bad-units.yml`                            | unit-typed strings without unit suffix  |
| `04-unknown-pin-constraint.yml`               | constraint tag not in the closed enum   |
| `05-template-field-needs-bit-or-bits.yml`     | template field missing `bit` / `bits`   |
| `06-clock-domain-no-source.yml`               | clock domain missing `source/sources`   |
| `07-select-register-missing-encoding.yml`     | `select_register` missing `encoding`    |

Run them all with:

```bash
python3 schema/validate.py schema/negative-tests
```

Each file produces a single, location-tagged error.

## Integration recipe (auto-extractors)

The auto-extractors in `alloy_data_extractor/emit/canonical_yaml.py`
already run a JSON-schema validator against the v1 schema.  Wiring v2.1
in alongside is one extra call per emitted file:

```python
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator

V21_SCHEMA = Path("proposals/canonical-v2-handcrafted/schema/alloy-device-v2_1.schema.json")

def validate_v21(payload: dict) -> None:
    schema = json.loads(V21_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload),
                    key=lambda e: list(e.absolute_path))
    if errors:
        details = "\n".join(
            f"  • {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors
        )
        raise ValueError(f"v2.1 schema validation failed:\n{details}")
```

Call `validate_v21(payload)` after the writer's compaction step but
before `yaml.dump`.  The extractor fails fast on shape drift instead
of letting a broken YAML land in `alloy-devices-yml`.

## When to bump the schema

Any of these requires a `v2.2` (additive) or `v3.0` (breaking) bump:

* New top-level required key                         — **breaking**
* New optional top-level key                          — additive
* New value in a closed enum (e.g. pin constraint)    — additive
* Removing / renaming an existing required key        — **breaking**
* Tightening an existing `additionalProperties: true` — **breaking**
* Loosening a pattern (e.g. `register_ref`)           — additive
