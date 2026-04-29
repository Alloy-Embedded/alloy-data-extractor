# DEFERRED — esp-idf cache empty + IR-projection coordination

## Why this archives without implementation

The proposal walks `components/soc/<chip>/include/soc/clk_tree_defs.h`
and `clk_tree_hal.c` from the esp-idf checkout to project the
ESP32-class clock tree.  `alloy-codegen/.cache/sources/esp-idf/`
exists but is empty — the esp-idf upstream needs to be staged
before any clock-tree extraction can run.

Even with the source staged, the canonical YAML schema
(`device.schema.json`) treats `clock_nodes` / `clock_selectors` /
`clock_gates` / `peripheral_clock_bindings` as permissive arrays.
Adding a richer ESP32 clock graph than the current 2-5 node
stub is fine schema-wise, but the codegen consumer's projection
of these arrays into the runtime clock contract has not been
verified against a 30-node ESP32 clock graph yet — the proposal's
"every field consumed already exists on `CanonicalDeviceIR`"
claim deserves a runtime-cpp-smoke pass before the YAMLs land.

## What's needed before this can land

- esp-idf checked out at a pinned SHA, with
  `components/soc/<chip>/include/soc/clk_tree_defs.h` and
  `components/soc/<chip>/clk_tree_hal.c` accessible.
- A runtime-cpp-smoke pass against a re-emitted esp32 YAML to
  confirm the rich clock graph round-trips through the
  `runtime_clock_config.hpp` emitter.
- A test fixture with the parsed `ClockTree` for at least
  esp32 / esp32c3 / esp32s3 so future esp-idf bumps trip a
  deliberate review.

## Where to look next

* `extractors/esp_idf.py` — current Espressif surface (peripherals
  + IRQ tables only).
* `data/source_pins.toml::espressif-esp-idf` — pin entry pinned
  at v5.3 but with no fetched cache.
