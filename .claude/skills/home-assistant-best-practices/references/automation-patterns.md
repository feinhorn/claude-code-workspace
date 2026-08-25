# Automation Patterns

This document covers native Home Assistant automation constructs that should be used instead of templates.

## Table of Contents
1. [Native Conditions](#native-conditions)
2. [Trigger Types](#trigger-types)
3. [Wait Actions](#wait-actions)
4. [Automation Modes](#automation-modes)
5. [Continue on Error](#continue-on-error)
6. [Repeat Actions](#repeat-actions)
7. [if/then vs choose](#ifthen-vs-choose)
8. [Trigger IDs](#trigger-ids)
9. [Disabling Automations](#disabling-automations)

---

## Native Conditions

### State Condition

```yaml
# Single state
condition: state
entity_id: light.living_room
state: "on"

# Multiple acceptable states (OR logic)
condition: state
entity_id: vacuum.robot
state:
  - "cleaning"
  - "returning"

# Attribute check
condition: state
entity_id: climate.thermostat
attribute: hvac_action
state: "heating"

# Duration check
condition: state
entity_id: binary_sensor.motion
state: "off"
for:
  minutes: 5
```

### Numeric State Condition

Always prefer over template conditions with `| float`.

```yaml
condition: numeric_state
entity_id: sensor.temperature
above: 25

condition: numeric_state
entity_id: sensor.battery
above: 20
below: 80

condition: numeric_state
entity_id: sun.sun
attribute: elevation
below: -6
```

### Time Condition

```yaml
# Time range (handles midnight crossing!)
condition: time
after: "22:00:00"
before: "06:00:00"

condition: time
after: "09:00:00"
before: "17:00:00"
weekday:
  - mon
  - tue
  - wed
  - thu
  - fri
```

### Sun / Zone / And / Or / Not Conditions

```yaml
condition: sun
after: sunset
after_offset: "00:30:00"

condition: zone
entity_id: person.john
zone: zone.home

condition: or
conditions:
  - condition: state
    entity_id: person.john
    state: "home"
  - condition: state
    entity_id: person.jane
    state: "home"

# Shorthand template condition (when template is necessary)
conditions:
  - "{{ trigger.to_state.attributes.brightness > 100 }}"
```

---

## Trigger Types

### State Trigger

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.motion
    to: "on"

  - trigger: state
    entity_id: light.porch
    to: "on"
    for:
      minutes: 30

  # Multiple entities
  - trigger: state
    entity_id:
      - binary_sensor.motion_kitchen
      - binary_sensor.motion_hallway
    to: "on"
```

### Numeric State / Time / Sun Triggers

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.temperature
    above: 25
    for:
      minutes: 5

  - trigger: time
    at: "07:00:00"

  - trigger: time_pattern
    minutes: "/5"

  - trigger: sun
    event: sunset
    offset: "-00:30:00"
```

### Event / MQTT Triggers

```yaml
# ZHA button
triggers:
  - trigger: event
    event_type: zha_event
    event_data:
      device_ieee: "00:11:22:33:44:55:66:77"
      command: "on"

triggers:
  - trigger: mqtt
    topic: "zigbee2mqtt/button/action"
    payload: "single"
```

**Multi-trigger guard for `trigger.event`:** In automations mixing event and non-event triggers, `trigger.event` is `LoggingUndefined` for non-event triggers. Use `trigger.platform == 'event'` as a guard:

```yaml
# CORRECT — guard prevents evaluating trigger.event on non-event triggers
conditions:
  - "{{ trigger.platform == 'event' and 'light.kitchen' in trigger.event.data.entity_id }}"
```

### Presence and Person Triggers and Conditions (Removed in 2026.5)

`entered_home`/`left_home` device triggers and `is_home`/`is_not_home` device conditions were **removed in 2026.5**. Use state triggers/conditions instead:

```yaml
# CORRECT — state trigger
triggers:
  - trigger: state
    entity_id: person.john
    to: "home"

# CORRECT — state condition
condition: state
entity_id: person.john
state: "home"
```

### Timer Entity Triggers (2026.5+)

```yaml
triggers:
  - trigger: event
    event_type: timer.finished
    event_data:
      entity_id: timer.cooking
```

---

## Wait Actions

### wait_for_trigger (Preferred)

Event-driven wait. More efficient than polling.

```yaml
- wait_for_trigger:
    - trigger: state
      entity_id: binary_sensor.door
      to: "off"
  timeout:
    minutes: 5
  continue_on_timeout: false

# Check result
- if:
    - "{{ not wait.completed }}"
  then:
    - action: notify.mobile_app
      data:
        message: "Door still open!"
```

### wait_template (Use Sparingly)

Polls until template is true. **Immediately continues if already true at wait start.**

```yaml
- wait_template: "{{ states('sensor.temperature') | float > 25 }}"
  timeout:
    minutes: 10
```

**Key difference:** `wait_for_trigger` waits for a *change*; `wait_template` waits for a *condition* (passes immediately if already true).

---

## Automation Modes

| Mode | Behavior | Best for |
|------|----------|----------|
| `single` (default) | New triggers ignored while running | One-shot notifications |
| `restart` | Stops current run, starts fresh | Motion lights with timeout |
| `queued` | Queues new triggers | Sequential processing, door locks |
| `parallel` | Runs multiple instances simultaneously | Per-entity actions |

```yaml
automation:
  - alias: "Motion light"
    mode: restart  # Re-trigger resets the timer
    triggers:
      - trigger: state
        entity_id: binary_sensor.motion
        to: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.hallway
      - wait_for_trigger:
          - trigger: state
            entity_id: binary_sensor.motion
            to: "off"
            for:
              minutes: 5
      - action: light.turn_off
        target:
          entity_id: light.hallway

automation:
  - alias: "Garage door"
    mode: queued
    max: 5
    ...

automation:
  - alias: "Window open too long"
    mode: parallel
    max: 10
    triggers:
      - trigger: state
        entity_id:
          - binary_sensor.window_bedroom
          - binary_sensor.window_kitchen
        to: "on"
        for:
          minutes: 30
    actions:
      - action: notify.mobile_app
        data:
          message: "{{ trigger.to_state.name }} has been open for 30 minutes"
```

---

## Continue on Error

```yaml
actions:
  - action: light.turn_on
    target:
      entity_id: light.patio
    continue_on_error: true  # Automation proceeds even if this fails
```

---

## Repeat Actions

```yaml
# Repeat N times
- repeat:
    count: 3
    sequence:
      - action: light.toggle
        target:
          entity_id: light.bedroom

# While condition
- repeat:
    while:
      - condition: state
        entity_id: binary_sensor.door
        state: "on"
    sequence:
      - action: notify.mobile_app
        data:
          message: "Door still open"
      - delay:
          minutes: 5

# For each item
- repeat:
    for_each:
      - "light.kitchen"
      - "light.bedroom"
    sequence:
      - action: light.turn_off
        target:
          entity_id: "{{ repeat.item }}"
```

---

## if/then vs choose

```yaml
# if/then/else — binary conditions
actions:
  - if:
      - condition: state
        entity_id: sun.sun
        state: "below_horizon"
    then:
      - action: light.turn_on
        target:
          entity_id: light.porch
    else:
      - action: light.turn_off
        target:
          entity_id: light.porch

# choose — multiple branches
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: "morning"
        sequence:
          - action: scene.turn_on
            target:
              entity_id: scene.morning
      - conditions:
          - condition: trigger
            id: "evening"
        sequence:
          - action: scene.turn_on
            target:
              entity_id: scene.evening
    default:
      - action: light.turn_off
        target:
          area_id: living_room
```

---

## Trigger IDs

```yaml
automation:
  - alias: "Multi-trigger automation"
    triggers:
      - trigger: state
        entity_id: binary_sensor.motion
        to: "on"
        id: "motion_on"
      - trigger: state
        entity_id: binary_sensor.motion
        to: "off"
        for:
          minutes: 5
        id: "motion_off"
    actions:
      - choose:
          - conditions:
              - condition: trigger
                id: "motion_on"
            sequence:
              - action: light.turn_on
                target:
                  entity_id: light.hallway
          - conditions:
              - condition: trigger
                id: "motion_off"
            sequence:
              - action: light.turn_off
                target:
                  entity_id: light.hallway
```

---

## Disabling Automations

### Method 1: Turn Off (Temporary)

```yaml
- action: automation.turn_off
  target:
    entity_id: automation.my_automation
  data:
    stop_actions: true  # default: true
```

Survives reload if automation has an `id:` field. Entity stays in state machine with state `off`.

### Method 2: Registry Disable (Permanent)

UI: Settings → Automations → open automation → ⋮ → Settings → Enabled toggle

Or via WebSocket: `config/entity_registry/update` with `{"disabled_by": "user"}` / `{"disabled_by": null}`

Requires `id:` field in `automations.yaml`. Entity removed from state machine entirely.

### AVOID: `enabled: false` in automations.yaml

```yaml
# AVOID — not a valid top-level key; automation loads as unavailable
- alias: My Automation
  enabled: false
```
