# Device Control Patterns

## Entity ID vs Device ID

**Always prefer `entity_id` over `device_id` in service calls and triggers.**

`device_id` is a HA internal identifier that **changes when a device is re-added** to HA, breaking automations silently. `entity_id` is user-controllable and stable across device re-adds.

**Exception:** Zigbee2MQTT autodiscovered device triggers are acceptable — Z2M manages the mapping.

---

## Service Calls Best Practices

Use the `target:` structure with `entity_id`, `area_id`, or `device_id`:

```yaml
# Single entity
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
    data:
      brightness_pct: 80
      color_temp_kelvin: 3000

# Multiple entities
actions:
  - action: light.turn_off
    target:
      entity_id:
        - light.kitchen
        - light.hallway

# Area targeting
actions:
  - action: light.turn_off
    target:
      area_id: living_room

# Dynamic entity from trigger
actions:
  - action: light.turn_on
    target:
      entity_id: "{{ trigger.entity_id }}"
```

**Important:** Parameters go inside `data:`, not at the action level. Placing them outside `data:` is a common error that breaks automations silently.

---

## Zigbee Button/Remote Patterns

### ZHA

Use `event` trigger with `device_ieee` (persistent across re-adds):

```yaml
triggers:
  - trigger: event
    event_type: zha_event
    event_data:
      device_ieee: "00:11:22:33:44:55:66:77"
      command: "toggle"
      # cluster_id: 6  # optional, for specificity
```

Get `device_ieee` from: Settings → Devices → [device] → look at Device info.

### Zigbee2MQTT

Use device trigger (autodiscovered) or MQTT trigger:

```yaml
# Device trigger (Z2M manages mapping — acceptable here)
triggers:
  - trigger: device
    domain: mqtt
    device_id: abc123def456
    type: action
    subtype: single

# MQTT trigger (most explicit)
triggers:
  - trigger: mqtt
    topic: "zigbee2mqtt/my_button/action"
    payload: "single"
```

---

## Domain-Specific Patterns

### Lights

```yaml
# Color temperature — use Kelvin (color_temp in mireds was removed in 2026.3)
actions:
  - action: light.turn_on
    target:
      entity_id: light.lamp
    data:
      brightness_pct: 75
      color_temp_kelvin: 4000  # NOT color_temp: <mireds>

# RGB color
actions:
  - action: light.turn_on
    target:
      entity_id: light.lamp
    data:
      rgb_color: [255, 100, 0]

# Transition
actions:
  - action: light.turn_on
    target:
      entity_id: light.lamp
    data:
      brightness_pct: 10
      transition: 30  # seconds
```

### Climate

```yaml
actions:
  - action: climate.set_temperature
    target:
      entity_id: climate.thermostat
    data:
      temperature: 22

  - action: climate.set_hvac_mode
    target:
      entity_id: climate.thermostat
    data:
      hvac_mode: "cool"  # heat, cool, heat_cool, auto, dry, fan_only, off

  - action: climate.set_preset_mode
    target:
      entity_id: climate.thermostat
    data:
      preset_mode: "away"
```

### Covers

```yaml
actions:
  - action: cover.set_cover_position
    target:
      entity_id: cover.blind
    data:
      position: 50  # 0 = closed, 100 = open

  - action: cover.open_cover
    target:
      entity_id: cover.garage_door
```

### Vacuum

```yaml
# Prefer area-based cleaning over vendor room IDs
actions:
  - action: vacuum.clean_area
    target:
      entity_id: vacuum.robot
    data:
      area_id:
        - kitchen
        - living_room

# Fallback: send_command with vendor IDs (less portable)
actions:
  - action: vacuum.send_command
    target:
      entity_id: vacuum.robot
    data:
      command: app_segment_clean
      params:
        segments: [16, 17]
```

### Notifications

```yaml
actions:
  - action: notify.mobile_app_iphone_max
    data:
      message: "Alert: {{ message }}"
      title: "Home Assistant"
      data:
        tag: "unique_tag"  # replaces previous notification with same tag
        url: /lovelace/main
```

---

## Presence Detection

State-based (not device triggers — those were removed in 2026.5):

```yaml
# Trigger
triggers:
  - trigger: state
    entity_id: person.john
    to: "home"

# Condition
condition: state
entity_id: person.john
state: "home"  # or "not_home" for away

# Zone-based
condition: zone
entity_id: person.john
zone: zone.work
```
