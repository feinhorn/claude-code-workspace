# Helper Selection Guide

Use built-in helpers and integrations instead of YAML template sensors or complex automations. When no dedicated helper covers your need, use the **template helper** (created via the UI / config-entry flow, not YAML `template:`).

## Menu-Based Helpers

Several helpers start with a sub-type menu. Submit `{"next_step_id": "<sub-type>"}` to the first step before fields become available.

| Helper | Sub-types |
|--------|-----------|
| `template` | `sensor`, `binary_sensor`, `button`, `switch`, `light`, `cover`, `fan`, `lock`, `select`, `number`, `image`, `vacuum`, `weather`, `alarm_control_panel`, `event`, `update` |
| `group` | `binary_sensor`, `button`, `cover`, `event`, `fan`, `light`, `lock`, `media_player`, `notify`, `sensor`, `switch`, `valve` |
| `random` | `sensor`, `binary_sensor` |

---

## Numeric Aggregation

### min_max — averaging/summing multiple sensors

```yaml
sensor:
  - platform: min_max
    name: "Average Temperature"
    type: mean  # min, max, mean, median, last, sum
    entity_ids:
      - sensor.temp_bedroom
      - sensor.temp_living
      - sensor.temp_kitchen
```

Ignores `unknown` states. Returns error if units differ.

### statistics — statistical analysis over time

```yaml
sensor:
  - platform: statistics
    name: "Temperature Change (5 min)"
    entity_id: sensor.temperature
    state_characteristic: change  # mean, median, stdev, value_min/max, count, etc.
    max_age:
      minutes: 5
    sampling_size: 50
```

---

## Rate and Change

### derivative — rate of change

```yaml
sensor:
  - platform: derivative
    name: "Power Rate of Change"
    source: sensor.power
    unit_time: min
    time_window:
      minutes: 5
```

### threshold — binary sensor at numeric threshold

```yaml
binary_sensor:
  - platform: threshold
    name: "High Temperature"
    entity_id: sensor.temperature
    upper: 25
    hysteresis: 1  # ON above 26, OFF below 24
```

---

## Time-Based Tracking

### utility_meter — consumption with periodic resets

```yaml
utility_meter:
  daily_energy:
    source: sensor.energy_consumption
    cycle: daily  # quarter-hourly, hourly, daily, weekly, monthly, quarterly, yearly
  monthly_energy:
    source: sensor.energy_consumption
    cycle: monthly
```

### history_stats — time/count in state

```yaml
sensor:
  - platform: history_stats
    name: "Lights on today"
    entity_id: light.living_room
    state: "on"
    type: time  # time, ratio, count
    start: "{{ now().replace(hour=0, minute=0, second=0) }}"
    end: "{{ now() }}"
```

### integration (Riemann sum) — power → energy

```yaml
sensor:
  - platform: integration
    name: "Solar Energy"
    source: sensor.solar_power
    unit_prefix: k
    unit_time: h
    method: left  # left, right, trapezoidal
    round: 2
```

---

## State Storage

```yaml
input_boolean:
  guest_mode:
    name: "Guest Mode"

input_number:
  target_temperature:
    name: "Target Temperature"
    min: 15
    max: 30
    step: 0.5
    unit_of_measurement: "°C"
    mode: slider  # slider, box

input_select:
  hvac_mode:
    name: "HVAC Mode"
    options: ["auto", "cool", "heat", "off"]

input_datetime:
  morning_alarm:
    name: "Morning Alarm"
    has_time: true
    has_date: false

counter:
  coffee_count:
    name: "Coffees Today"
    initial: 0
    step: 1
    restore: true

timer:
  laundry:
    name: "Laundry Timer"
    duration: "01:00:00"
    restore: true
```

---

## Scheduling

```yaml
# schedule helper — weekly on/off
schedule:
  work_hours:
    name: "Work Hours"
    monday:
      - from: "09:00:00"
        to: "17:00:00"

# tod — binary sensor based on time/sunrise/sunset
binary_sensor:
  - platform: tod
    name: "Night Time"
    after: sunset
    after_offset: "01:00:00"
    before: sunrise
```

---

## Entity Grouping

```yaml
group:
  all_lights:
    name: "All Lights"
    entities:
      - light.living_room
      - light.bedroom
    all: false  # ON if ANY member on (use true for ALL-must-be-on)
```

Config-entry groups (UI) are menu-based: submit `{"next_step_id": "<sub-type>"}` first, then provide `entities`. Sensor groups also require `type` (last, first_available, max, mean, median, min, product, range, stdev, sum).

---

## Data Smoothing

```yaml
sensor:
  - platform: filter
    name: "Filtered Temperature"
    entity_id: sensor.outdoor_temp
    filters:
      - filter: outlier
        window_size: 4
        radius: 2.0
      - filter: lowpass
        time_constant: 10
      - filter: time_simple_moving_average
        window_size: "00:05"
        precision: 2
```

Filter types: `lowpass`, `outlier`, `range`, `throttle`, `time_throttle`, `time_simple_moving_average`.

The UI config flow creates one filter per entry. Use YAML for chained pipelines.

---

## Climate Control

```yaml
climate:
  - platform: generic_thermostat
    name: "Bedroom"
    heater: switch.bedroom_heater
    target_sensor: sensor.bedroom_temperature
    ac_mode: false
    cold_tolerance: 0.3
    hot_tolerance: 0.3

humidifier:
  - platform: generic_hygrostat
    name: "Bathroom Dehumidifier"
    device_class: dehumidifier
    humidifier: switch.bathroom_fan
    target_sensor: sensor.bathroom_humidity
```

---

## Domain Conversion

`switch_as_x` — expose a switch as a different domain (light, cover, fan, lock, siren, valve). UI-only, no YAML equivalent. Original switch entity is hidden.

---

## Template Helpers

When no dedicated helper fits, use the **template helper** (UI / config flow), not YAML `template:` platform sensors.

```yaml
# Equivalent YAML (for reference — prefer the UI helper)
template:
  - sensor:
      - name: "Solar Net"
        unique_id: solar_net
        state: "{{ states('sensor.solar_production') | float(0) - states('sensor.house_consumption') | float(0) }}"
        unit_of_measurement: "W"
        device_class: power
        state_class: measurement
        availability: >
          {{ states('sensor.solar_production') not in ['unavailable', 'unknown']
             and states('sensor.house_consumption') not in ['unavailable', 'unknown'] }}
```

---

## Decision Matrix

| Need | Use | Not |
|------|-----|-----|
| Average multiple sensors | `min_max` (mean) | Template math |
| Sum multiple sensors | `min_max` (sum) | Template math |
| Average over time | `statistics` | Template tracking history |
| Rate of change | `derivative` | Template delta |
| On/off at threshold | `threshold` | Template binary sensor |
| Consumption per period | `utility_meter` | Counter + reset automation |
| Time in state | `history_stats` | Template timestamps |
| Power → energy | `integration` | Template approximation |
| User toggle | `input_boolean` | — |
| User number | `input_number` | — |
| User selection | `input_select` | — |
| Count events | `counter` | input_number + automation |
| Countdown timer | `timer` | delay + input_datetime |
| Weekly schedule | `schedule` | Template weekday checks |
| Time-of-day mode | `tod` | Template time checks |
| Any-on / all-on | `group` | Template binary sensor |
| Smooth noisy sensor | `filter` | statistics mean |
| Throttle update rate | `filter` (throttle/time_throttle) | Custom automation |
| Thermostat from switch | `generic_thermostat` | Automation with hysteresis |
| Switch as light/cover/lock | `switch_as_x` | Template light/cover |
| Random value | `random` | Template range() |
| Custom logic | `template` helper (UI flow) | YAML `template:` platform |
