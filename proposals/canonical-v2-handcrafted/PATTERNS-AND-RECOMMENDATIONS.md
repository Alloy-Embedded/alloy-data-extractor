# Cross-vendor patterns & recommendations

After hand-writing five canonical-v2 YAMLs (STM32F103, ATmega328P,
ESP32-WROOM-32, nRF52840, RP2040 / Pico) on the same day with the same
conventions, the following patterns and v1-vs-v2 deltas surfaced.

| Chip                 | Lines | Bytes |
|----------------------|------:|------:|
| stm32f103c8t6.yml    |  598  | 22 KB |
| esp32-wroom32.yml    |  489  | 19 KB |
| nrf52840.yml         |  497  | 17 KB |
| rp2040.yml           |  513  | 19 KB |
| atmega328p.yml       |  444  | 14 KB |
| **avg / chip**       | **508** | **18 KB** |

For comparison, the auto-extracted canonical-v1 YAMLs (post-Phase-2
`provenance_defaults` compaction) range **70 KB – 3 MB** per chip.  The
hand-crafted v2 is **4-150× smaller** and contains every fact codegen
needs for blink / UART / SPI / I²C / ADC / timer codepaths.

The slimming is not magic — it's two design decisions:

1. **Templates collapse register layouts.**  STM32F103 has 3× USART, 2× SPI,
   2× I²C, 4× timers — same IP layout per group.  v1 emits the full
   register set 11 times; v2 emits each IP's layout once and instances
   reference it by name.
2. **Codegen-relevant fields only.**  `bit_offset` for every bit isn't
   needed — only the bits codegen flips during init (`cr1.ue`, `sr.txe`,
   …).  ~95% of the SVD's 4 000+ register-field rows per STM32 chip never
   reach codegen.

## Patterns that emerged

### 1. Templates are universal

Every chip benefits from `templates.<ip>`.  Cross-vendor share rate of
the SAME named template:

| Template          | Reused by                              |
|-------------------|----------------------------------------|
| `gpio`            | All 5                                  |
| `uart` / `usart`  | All 5 (different field names)          |
| `spi` / `spim`    | 4 (AVR uses simpler shape)             |
| `i2c` / `twi` / `twim` | 5                                 |
| `adc` / `saadc`   | 5                                      |
| `timer*`          | 5 (counter widths differ)              |
| `pwm` / `ledc`    | 3 (RP2040, ESP32 explicit; STM32 inside `timer_general`) |
| `dma_controller`  | 3 (STM32, RP2040, ESP32-S3)            |
| `pio`             | RP2040 only                            |

→ canonical-v2 should **standardise template names** across vendors so
codegen's emitter dispatches by template id (e.g. `usart` vs `uarte` vs
`uart-primecell` — each gets its own backend).

### 2. Pin-mux models split into two families

| Family          | Chips             | Format                                    |
|-----------------|-------------------|-------------------------------------------|
| **fixed-AF**    | STM32F1, AVR      | `pin_options.tx: [{pin: PA9, remap: 0}]`  |
| **matrix-PSEL** | ESP32, nRF52      | `pin_options.tx: { matrix: true }` / `{ psel: true }` |
| **fn-select**   | RP2040            | `pin_options.tx: [{ pin: GPIO0, func: 2 }]` (small set per signal) |

→ canonical-v2 should accept all three shapes natively.  The codegen's
pin-router asks `pin_options.<sig>` and dispatches:

```python
if isinstance(opts, list):
    fixed_or_fn_select(opts)            # STM32 / RP2040
elif opts.get("matrix"):
    gpio_matrix(opts)                   # ESP32
elif opts.get("psel"):
    psel_register(opts)                 # nRF52
```

### 3. Multi-core is core-level metadata

ESP32 (asymmetric LX6 dual-core) and RP2040 (symmetric M0+ dual-core)
both fit cleanly under `identity.core.multicore`.  Single-core chips
omit the field; codegen treats absence as `single_core`.

### 4. Address spaces matter for Harvard chips

AVR's flash + SRAM live in different address spaces (program vs data).
v1 silently coerces; v2 carries `address_space: program | data | eeprom
| fuse | signature` so the linker emitter knows whether `0x0000` means
flash or SRAM.

### 5. External flash needs a `backing` tag

ESP32 + RP2040 have NO on-die flash.  The "flash" region is an XIP
window over external SPI/QSPI flash.  v2 marks these with:

```yaml
- { id: flash_xip, base: 0x10000000, size: 2MB, access: rx,
    role: xip-cached, backing: external-qspi-flash }
```

so codegen emits the right boot stage 2 + linker placement.

### 6. Mutex groups for shared peripheral bases

nRF52's SPIM/TWIM/UARTE share a single base address per group — at most
one of each pair is enabled at a time.  v2 captures this with
`mutex_group: <name>` on each instance; codegen's pin-router rejects
configurations that turn on two siblings of the same group.

### 7. Interrupt model varies wildly

| Chip      | Model                                          |
|-----------|------------------------------------------------|
| STM32F1   | Fixed NVIC table, 60 IRQs                      |
| ATmega328P| Fixed AVR vector table, 26 vectors             |
| nRF52840  | Fixed NVIC, 48 IRQs (some shared via mutex_group) |
| RP2040    | Fixed NVIC, 26 IRQs                            |
| ESP32     | **Matrix** — peripheral signals route to any of 32 internal IRQs at runtime |

→ canonical-v2 has `interrupts.matrix: true` flag for ESP32-style chips,
and a flat list for everyone else.  Codegen's startup emitter checks
`matrix` first and either generates the routing init code or just the
vector table.

### 8. Templates carry `tasks`/`events`/`shorts` for Nordic-style IPs

Nordic peripherals are task/event-driven (no bit-by-bit configuration).
The `registers` map naturally absorbs `tasks_starttx` / `events_rxdrdy`
without needing a special section — same shape, just different register
roles.

## Recommendations to feed back into the codebase

### Immediate (low risk, high value)

1. **Adopt `templates:` section** in canonical-v1 schema 1.6.0.  Every
   peripheral's register layout moves from per-row `register_fields[]`
   blocks (5 936 entries on stm32g0b1re!) to a per-IP-version template
   referenced by `peripherals[].template`.  Estimated 80-95 % shrink on
   the canonical YAMLs even after Phase-2 dedup.

2. **`address_space`** on `memory[]` rows.  Without it AVR will never
   work cleanly.

3. **`multicore`** under `identity.core` — replaces today's ad-hoc
   `secondary_core_release` register flag and the half-modeled
   ESP32 / RP2040 shapes.

4. **Pin-mux family flag** (`fixed-af` / `matrix` / `psel` / `fn-select`)
   on each peripheral or template.  Today the codegen plumbs it via
   chip-name pattern matching, which scales linearly with admitted
   chips.

### Medium-term (schema bump 2.0.0)

5. **Drop `register_field_enumerations` flat list**.  Move enum values
   into the template's `fields` map under each field's
   `enum: { name: value }` sub-key.  Today's flat list is 6 829 rows on
   stm32g0b1re — most reachable from the field's `bits:` range plus a
   small per-field enum.

6. **`pin_options` schema unification.**  Today the IR has three
   different shapes for the three pin-mux families.  Pick one
   (`{matrix, psel, options: [...]}`) and have all extractors normalise
   into it.

7. **`mutex_group`** to formalise nRF52-style shared-base peripherals
   (and, soon, STM32H7 dual-mode SPI/I²S, NXP ChipSelect-shared LPSPI
   instances, …).

### Aspirational (schema 3.0.0)

8. **`system_examples`** as a first-class field.  The hand-written ones
   here double as integration tests + worked examples.  Run them through
   codegen on every CI and assert byte-stable output.

9. **Cross-vendor template registry**.  Today `usart` means different
   things on STM vs Nordic vs RP2040.  We could split into
   `usart-stm32-v1`, `uart-primecell-pl011`, `uarte-nordic-v1`, etc., so
   codegen's emitter dispatches by IP-version, not by chip name.

## Files in this proposal

```
proposals/canonical-v2-handcrafted/
├── README.md                          ← format spec & rationale
├── PATTERNS-AND-RECOMMENDATIONS.md    ← this file
├── stm32f103c8t6.yml                  ← STM32F103 (598 lines, 22 KB)
├── atmega328p.yml                     ← Arduino UNO (444 lines, 14 KB)
├── esp32-wroom32.yml                  ← ESP32 module (489 lines, 19 KB)
├── nrf52840.yml                       ← Nordic BLE chip (497 lines, 17 KB)
└── rp2040.yml                         ← Raspberry Pico (513 lines, 19 KB)
```

Total: 2 541 YAML lines, 91 KB across five very different MCUs.  The
auto-extracted v1 equivalents total ≈ 13 MB — a **~140× expansion** that
v2 reclaims by template-and-reference + dropping never-read fields.
