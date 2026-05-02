# canonical-v2.1 — changelog

Released 2026-05-01.

Applies the 13 deltas surfaced by the audit in `AUDIT-vs-V1.md` to all
five hand-crafted YAMLs.  The format remains `alloy.device.v2.1`.

## Per-delta status

| # | Delta                                         | STM32 | AVR | ESP32 | nRF52 | RP2040 |
|---|-----------------------------------------------|:-----:|:---:|:-----:|:-----:|:------:|
| 1 | `pin_constraints` (analog-only, strapping…)   | ✅    | ✅  | ✅    | ✅    | ✅     |
| 2 | Field `enum:` sub-keys (named bit values)     | ✅    | ✅  | ✅    | ✅    | ✅     |
| 3 | ADC `calibration:` ROM block                  | ✅    | n/a | n/a   | n/a   | n/a    |
| 4 | ADC `external_triggers:`                      | ✅    | n/a | n/a   | n/a   | n/a    |
| 5 | I²C `timing_presets:` per (speed × clock)     | ✅    | n/a | n/a   | n/a   | n/a    |
| 6 | Timer `trigger_sources:` field-value table    | ✅    | ✅  | n/a   | n/a   | n/a    |
| 7 | Timer `master_outputs:` (TRGO MMS)            | ✅    | ✅  | n/a   | n/a   | n/a    |
| 8 | `timer_advanced` template (break + dead-time) | ✅    | n/a | n/a   | n/a   | n/a    |
| 9 | `peripherals[].ip_version:` tag               | ✅    | n/a | n/a   | n/a   | n/a    |
| 10| `clock.profiles[]` named profiles             | ✅    | ✅  | ✅    | ✅    | ✅     |
| 11| Per-instance `max_clock_override`             | ✅    | n/a | n/a   | n/a   | n/a    |
| 12| Clock-domain `select_register/select_task`    | ✅    | ✅  | ✅    | ✅    | ✅     |
| 13| `templates[].fields` opt-in subset contract   | ✅    | ✅  | ✅    | ✅    | ✅     |

`n/a` = the chip's hardware doesn't have the feature (e.g. AVR has no
ADC calibration ROM; nRF52 has no advanced timer with break inputs).

## Size impact

| Chip                 | v2 lines | v2.1 lines | Δ      |
|----------------------|---------:|-----------:|-------:|
| stm32f103c8t6.yml    |     598  |       810  | +35 %  |
| atmega328p.yml       |     444  |       509  | +15 %  |
| esp32-wroom32.yml    |     489  |       537  | +10 %  |
| nrf52840.yml         |     497  |       569  | +14 %  |
| rp2040.yml           |     513  |       594  | +16 %  |
| **TOTAL**            |  **2 541** | **3 019** | **+19 %** |

The bulk of v2's 19% growth comes from STM32 (35%) — that chip carries
all eight ST-specific deltas (3, 4, 5, 6, 7, 8, 9, 11).  The other four
chips picked up only the four cross-vendor deltas (1, 2, 10, 12, 13)
plus delta 6 on AVR.  Even at v2.1 the total payload is 128 KB across
five very different MCUs — a **~100× reduction** vs the auto-extracted
v1 of equivalent chips.

## Highlights — what the deltas unlocked

* **STM32** ADC instances now carry the calibration ROM
  (`vrefint @ 0x1FFFF7BA`, `ts_cal_low @ 0x1FFFF7B8`, slope from
  datasheet) and the EXTSEL field-value table for triggered conversion.
  Codegen can now emit `convert_to_celsius(raw)` and `start_on(timer3.trgo)`
  helpers without consulting external tables.

* **STM32 I²C** timing presets are now first-class
  (`timing_presets[]: {speed, source_clock, ccr, trise}`).  Codegen no
  longer needs to run the AN4235 timing solver in C++ at compile time.

* **STM32 advanced timer** (TIM1) gets the `timer_advanced` template
  with `break_inputs`, `deadtime_options` (DTG prescaler+count tables),
  and the BDTR register fields — every PWM-with-dead-time codepath now
  has the bit-flips it needs.

* **AVR** clock prescaler + source select are explicit
  (`prescaler_register: CLKPR.CLKPS`, `select_register: FUSE.LOW.CKSEL`).
  The Arduino-default profile (`uno-default-16mhz`) is named.

* **ESP32** clock-source select + DPORT.SOC_CLK_SEL are explicit;
  `pll-240mhz`, `pll-160mhz`, `xtal-direct-40mhz` are named profiles.

* **nRF52** uses a `select_task:` (instead of `select_register:`)
  for HFCLK because the source switch is task-driven on Nordic — same
  schema slot, different semantics.

* **RP2040** clock-domain `auxsrc_register:` separates the AUXSRC mux
  from the SRC mux (faithful to the actual `CLOCKS_CLK_SYS_CTRL` layout).

* **Pin constraints** harmonised across vendors:
  `[analog-only | analog-capable | strapping | flash-reserved | nfc-default
  | lfxo-bond | input-only | rtc | reset | debug-default | boot |
  oscillator | power | chip-enable | module-reserved | low-drive]`.

## What's still ahead (v2.2 candidates)

* Cross-vendor template namespace (`usart-stm32-v1`, `uart-primecell-pl011`,
  `uarte-nordic-v1`).  Today every chip declares its own `usart` /
  `uart` / `uarte` template; rewiring them under a registry would let
  codegen pick the backend by IP-version, not by chip name.
* `system_examples:` as a tested artifact — run codegen on every CI and
  byte-compare against golden artifacts.
* Schema validator — declarative JSON-schema for v2.1 so the
  auto-extractors fail fast on shape drift.
