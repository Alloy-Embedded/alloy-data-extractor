## ADDED Requirements

### Requirement: The modm-devices extractor SHALL project Timer + PWM tier data

When a device's modm-devices descriptor carries
`<driver name="timer">` blocks, the extractor SHALL parse the
embedded prescaler / trigger / master-output / capability
metadata and project it onto the canonical IR's
`timer_prescaler_options`, `timer_trigger_sources`,
`timer_master_outputs`, `timer_mode_flags`,
`pwm_alignment_options`, and `pwm_break_inputs` fields.  Devices
without modm timer blocks (non-STM32 ARM Cortex-M parts) SHALL
be skipped silently — those vendors fill the same fields
through their own extractors.

#### Scenario: STM32G0B1 timers project full ITR + master matrix

- **WHEN** the modm extractor processes `stm32g0b1re`
- **THEN** the resulting canonical IR's `timer_trigger_sources`
  SHALL contain at least 8 entries
  (`ITR0`, `ITR1`, `ITR2`, `ITR3`, `TI1F_ED`, `TI1FP1`,
  `TI2FP2`, `ETRF`)
- **AND** `timer_master_outputs` SHALL contain at least 6
  entries (`Reset`, `Enable`, `Update`, `ComparePulse`,
  `OC1Ref`, `OC2Ref`)

#### Scenario: STM32F4 advanced timers expose dead-time + repetition counter

- **WHEN** the modm extractor processes `stm32f405rg`
- **THEN** the resulting canonical IR's `timer_mode_flags` for
  TIM1 SHALL set `supports_repetition_counter=True`,
  `supports_dma_burst=True`, `supports_xor_input=True`
- **AND** `pwm_alignment_options` SHALL carry edge and three
  center-aligned modes for TIM1
