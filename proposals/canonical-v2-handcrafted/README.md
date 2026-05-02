# canonical-v2.1 — hand-crafted reference

Five YAMLs written **by hand**, on the same day, by the same author, with
the same conventions, for five popular MCUs.  Goal: settle on a target
shape so the auto-extractors converge on it instead of carrying every
upstream source's idiosyncrasies forward.

> **v2.1** (2026-05-01): added the 13 deltas surfaced by the
> [audit vs v1](AUDIT-vs-V1.md) — `pin_constraints`, field `enum:`
> sub-keys, ADC `calibration:` ROM, ADC `external_triggers:`, I²C
> `timing_presets:`, timer `trigger_sources:` / `master_outputs:`,
> `timer_advanced` extension for break + dead-time, `ip_version:`,
> `clock.profiles[]`, per-instance `max_clock_override`, clock-domain
> `select_register:` / `auxsrc_register:` / `select_task:`, and the
> opt-in-subset contract on `templates.<ip>.fields`.
>
> **schema validator** (2026-05-01): JSON-schema Draft 2020-12 for
> `alloy.device.v2.1` lives at `schema/alloy-device-v2_1.schema.json`
> with a Python CLI at `schema/validate.py`.  All five hand-crafted
> YAMLs validate clean; seven negative tests under
> `schema/negative-tests/` prove the schema rejects common drift
> classes (bad units, missing required sections, unknown pin
> constraints, half-populated template fields, clock domains without
> a source, `select_register` missing an encoding).  See
> `schema/README.md` for invocation + integration with the
> auto-extractors.

| Vendor      | Chip                    | Family    | Core              | Flash | RAM   | Lines (v2.1) |
|-------------|-------------------------|-----------|-------------------|-------|-------|-------------:|
| ST          | STM32F103C8T6           | stm32f1   | Cortex-M3         | 64KB  | 20KB  | 810  |
| Microchip   | ATmega328P              | avr-mega  | AVR (8-bit)       | 32KB  | 2KB   | 509  |
| Espressif   | ESP32 (WROOM-32)        | esp32     | Xtensa LX6 ×2     | 4MB*  | 520KB | 537  |
| Nordic      | nRF52840                | nrf52     | Cortex-M4F        | 1MB   | 256KB | 569  |
| Raspberry   | RP2040 (Pico)           | rp2040    | Cortex-M0+ ×2     | 2MB*  | 264KB | 594  |
| **TOTAL**   |                         |           |                   |       |       | **3 019** |

*\* External QSPI flash mapped XIP — codegen generates the linker script around it.*

## Design rationale

### 1. One source of truth per fact

Every datum appears in exactly one place.  No more `peripheral: "GPIOA"` plus
`register_id: "register:gpioa:moder"` plus `register_peripheral: "GPIOA"` —
the row's own `id` already encodes the peripheral.

### 2. Templates collapse repetition

Every chip with a USART has the SAME register layout (`SR/DR/BRR/CR1/CR2/...`)
across all instances.  We define the layout **once** under `templates.usart`
and have `usart1`, `usart2`, … reference it.  A single STM32F103 saves
~200 lines this way; an STM32H7 with 9× USARTs saves ~2 000 lines.

The template carries:

* `capabilities`     — what the IP can do (`tx, rx, dma, smartcard, …`)
* `options`          — enumerated config knobs (`data_bits, parity, …`)
* `registers`        — `<name>: { offset: 0xNN }` map
* `fields`           — only the bits codegen actually flips
                       (`cr1.ue`, `sr.txe`, etc.)

### 3. Top-level provenance only

Per-row provenance was 30-50 % of every YAML in canonical-v1.  V2 has one
`provenance:` block at the top of the file.  Per-row provenance only
appears as an *override* when a single row came from a different source
than the rest of the file (rare; STM32 family overlay being the only
realistic case).

### 4. Cross-vendor field names

Wherever a concept exists across vendors, we use the same key:

| Concept              | Field path                              |
|----------------------|-----------------------------------------|
| Memory region        | `memory[].id / .base / .size / .access` |
| Oscillator frequency | `clock.oscillators.<name>.freq`         |
| Peripheral instance  | `peripherals[].id / .template / .base`  |
| Clock-enable bit     | `peripherals[].rcc.en`                  |
| IRQ slot             | `peripherals[].irq.{num,name}`          |
| Pin↔signal           | `peripherals[].pin_options.<sig>`       |
| DMA channel          | `peripherals[].dma.{tx,rx}`             |

Vendors that don't have the concept simply omit the field.  Codegen never
guesses; absence is meaningful.

### 5. Units in the YAML

`64KB`, `72MHz`, `2MB`, `0x08000000` instead of `64`, `72000000`,
`2097152`, `134217728`.  The parser normalises to canonical scalars
(`bytes`, `Hz`) so the IR is still numeric, but the YAML stays human.

### 6. No diagnostic echo fields

If `register_id` resolves to `(peripheral, register_name, offset)`, we
do not also emit them as separate strings.  Codegen consumers that need
the breakdown can call a helper.

## Layout cheat-sheet (v2.1)

```yaml
schema: alloy.device.v2.1

identity:        # vendor / family / device / package / core (+ multicore)
provenance:      # primary + secondary sources, hand vs auto, date
memory: [...]    # flash, ram, ccmram, … — drives linker.ld
                 # plus address_space + backing for Harvard / XIP chips

clock:
  oscillators: { hsi, hse, lsi, lse, … }
  pll:         { … }
  domains:
    - id: sysclk
      sources: [...]
      max: 72MHz
      select_register: { reg, field, encoding: { name: value, … } }   # v2.1 delta 12
  profiles:                                                            # v2.1 delta 10
    - { id: post-reset, kind: post-reset, … }
    - { id: pll-hse-72mhz, kind: recommended, … }
  reset_state: { sysclk_source, sysclk_freq }

templates:       # gpio, usart, spi, i2c, timer_general, timer_advanced, adc, …
  <ip>:
    capabilities: [...]
    options: { ... }
    trigger_sources: { itr0: 0, itr1: 1, … }     # v2.1 delta 6 (timers)
    master_outputs:  { reset: 0, enable: 1, … }   # v2.1 delta 7 (timers)
    deadtime_options: [...]                        # v2.1 delta 8 (advanced)
    registers: { <name>: { offset: 0xNN }, ... }
    fields:    { <reg>.<field>: { bit/bits: ..., enum: { … } } }   # v2.1 delta 2
    # ↑ opt-in subset — codegen contract that the listed names are bit-key-able
    #   The full register catalogue stays in provenance.primary (SVD/ATDF).

peripherals:     # one entry per silicon instance
  - id:   <gpioa | usart1 | timer3 | …>
    template: <ip>
    ip_version: <vendor-specific-tag>            # v2.1 delta 9
    base: 0x...
    bus: <ahb | apb1 | apb2 | …>
    rcc:  { en: <REG.BIT>, rst: <REG.BIT> }
    irq:  { num: N, name: <SYMBOL> }
    dma:  { tx: { ctrl, channel }, rx: { ctrl, channel } }
    pin_options: { tx: [{pin: PA9, remap: 0}], rx: [...] }
    max_clock_override: 36MHz                     # v2.1 delta 11
    # ADC-specific (v2.1 deltas 3 + 4):
    calibration:
      vrefint:    { rom_addr: 0x..., nominal_mv: 3300 }
      ts_cal_low: { rom_addr: 0x..., temp_celsius: 30 }
      ts_cal_high:{ rom_addr: 0x..., temp_celsius: 130 }
    external_triggers:
      regular:  [{ source, extsel, polarity }]
      injected: [{ source, jextsel }]
    # I²C-specific (v2.1 delta 5):
    timing_presets:
      - { speed: 100kHz, source_clock: 16MHz, timingr: 0x... }

pinout:          # per-package pin function map
  - { pin: 14, signal: PA0, ft: true,
      default_function: gpio,
      constraints: [analog-capable | strapping | flash-reserved | … ] }   # v2.1 delta 1

interrupts:      # vector table — one row per IRQ
  - { num: 0, name: WWDG_IRQHandler }

system_examples: # OPTIONAL — golden config snippets for tests
  blink_pa5:
    clock: { sysclk: 72MHz, source: pll_main, hse: 8MHz, mul: 9 }
    gpio:  { port: gpioa, pin: 5, mode: output, speed: 50MHz }
```
