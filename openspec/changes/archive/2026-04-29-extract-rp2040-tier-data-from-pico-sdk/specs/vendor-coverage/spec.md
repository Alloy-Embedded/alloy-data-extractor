## ADDED Requirements

### Requirement: The rp2040 extractor SHALL project I2C / PWM / Timer tier data

The rp2040 extractor SHALL parse the pico-sdk's `hardware_i2c`,
`hardware_pwm`, and `hardware_timer` headers and SHALL populate
`device.i2c_speed_options`, `device.i2c_timing_presets`,
`device.i2c_mode_flags`, `device.pwm_alignment_options`,
`device.pwm_mode_flags`, `device.timer_master_outputs`, and
`device.timer_mode_flags` for every admitted RP2040 device.

#### Scenario: rp2040 advertises three I2C speeds

- **WHEN** the rp2040 extractor processes the rp2040 device
- **THEN** the resulting canonical IR's `i2c_speed_options`
  SHALL contain at least 3 entries: 100 kHz (`standard`),
  400 kHz (`fast`), and 1 MHz (`fast_plus`)
- **AND** `i2c_timing_presets` SHALL contain at least one
  entry per (speed, source-clock) pair the pico-sdk supports

#### Scenario: rp2040 PWM declares edge + center-aligned modes

- **WHEN** the rp2040 extractor processes the rp2040 device
- **THEN** `device.pwm_alignment_options` SHALL contain at
  least 2 entries (edge, center-aligned)
- **AND** `device.pwm_mode_flags` SHALL set
  `supports_combined_pwm=True`,
  `supports_asymmetric_pwm=True`,
  `supports_deadtime=False`,
  `supports_break_input=False`

#### Scenario: rp2040 timer exposes 4 alarm comparators

- **WHEN** the rp2040 extractor processes the rp2040 device
- **THEN** `device.timer_master_outputs` SHALL contain at
  least 4 entries (one per alarm), with
  `(name="ALARM0", field_value=0)` through
  `(name="ALARM3", field_value=3)`
- **AND** `device.timer_mode_flags` SHALL set
  `supports_dma_burst=True` (the alarm DREQ paths)
