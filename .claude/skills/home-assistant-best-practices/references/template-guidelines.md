# Template Guidelines

**Core rule:** Templates are for cases where no native construct or built-in helper exists. Always check `references/helper-selection.md` first.

## When Templates ARE Appropriate

- Dynamic service data that depends on trigger context (e.g., `message: "{{ trigger.to_state.name }} opened"`)
- Processing raw data from MQTT or REST sources that has no native integration
- Accessing trigger-specific variables (`trigger.to_state`, `trigger.from_state`, `trigger.event.data`)
- Complex conditional logic involving multiple entities with no native `and`/`or` equivalent
- Attribute extraction where no native condition covers an attribute check
- Date/time arithmetic (`as_timestamp`, `timedelta`, `now()`)

## When NOT to Use Templates

| Template pattern | Use instead |
|-----------------|-------------|
| `{{ states('x') \| float > 25 }}` condition | `condition: numeric_state` with `above: 25` |
| `{{ is_state('x', 'on') and is_state('y', 'on') }}` | `condition: and` with state conditions |
| `{{ now().hour >= 9 }}` | `condition: time` with `after: "09:00:00"` |
| Template sensor averaging multiple sensors | `min_max` helper |
| Template binary sensor at threshold | `threshold` helper |
| Template tracking time in state | `history_stats` helper |
| `wait_template` for state condition | `wait_for_trigger` with state trigger |

## Template Sensor Best Practices

Always include:
- `unique_id:` — required for UI customization and entity registry management
- `availability:` — prevents unknown states propagating downstream
- `state_class:` — enables long-term statistics for numeric sensors

```yaml
template:
  - sensor:
      - name: "Solar Net Power"
        unique_id: solar_net_power
        state: >
          {{ states('sensor.solar_production') | float(0)
             - states('sensor.house_consumption') | float(0) }}
        unit_of_measurement: "W"
        device_class: power
        state_class: measurement
        availability: >
          {{ states('sensor.solar_production') not in ['unavailable', 'unknown', 'none']
             and states('sensor.house_consumption') not in ['unavailable', 'unknown', 'none'] }}
```

## Safe Coding Patterns

**Always use safe state access:**
```yaml
# CORRECT — safe, returns 'unavailable' if entity missing
states('sensor.temperature')

# AVOID — raises UndefinedError if entity missing
states.sensor.temperature.state
```

**Always provide defaults for numeric conversions:**
```yaml
# CORRECT
{{ states('sensor.value') | float(0) }}
{{ states('sensor.value') | int(0) }}

# AVOID — raises error if state is non-numeric
{{ states('sensor.value') | float }}
{{ states('sensor.value') | int }}
```

**Check availability before operations:**
```yaml
availability: >
  {{ states('sensor.x') not in ['unavailable', 'unknown', 'none']
     and states('sensor.y') not in ['unavailable', 'unknown', 'none'] }}
```

Or use `has_value()`:
```yaml
{{ states.sensor.x.state | has_value }}
```

## Trigger-Based Templates for Efficiency

Use trigger-based templates when the sensor should only update on specific events, not on every state change of every referenced entity:

```yaml
template:
  - trigger:
      - platform: state
        entity_id: binary_sensor.valve
        from: "on"
        to: "off"
    sensor:
      - name: "Last Run Duration"
        unique_id: last_run_duration
        unit_of_measurement: "s"
        state: >
          {{ ((trigger.to_state.last_changed | as_timestamp)
              - (trigger.from_state.last_changed | as_timestamp)) | int(0) }}
```

## Common Patterns

**Conditional display value:**
```yaml
state: >
  {% if is_state('binary_sensor.door', 'on') %}
    Open
  {% else %}
    Closed
  {% endif %}
```

**Safe numeric calculation with max/min:**
```yaml
state: >
  {{ [0, (target - current) / 100 * volume] | max | round(2) }}
```

**Multi-line template (use `>` for readability):**
```yaml
state: >
  {% set val = states('sensor.x') | float(0) %}
  {% set factor = states('input_number.factor') | float(1) %}
  {{ (val * factor) | round(2) }}
```
