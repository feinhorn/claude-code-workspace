---
name: ha-dashboard-yaml
description: Write and fix Home Assistant Lovelace dashboard YAML using the correct syntax for the installed card stack. Use this skill any time you are writing, editing, or debugging Lovelace YAML — including card configs, grid layouts, ApexCharts, Mushroom, button-card, layout-card, or any dashboard element. Also use when the user pastes dashboard YAML that isn't rendering correctly, throws a card error, or produces unexpected layout. Triggers on: 'dashboard', 'lovelace', 'card', 'apexcharts', 'mushroom', 'layout', 'grid_options', 'views', 'yaml mode'.
---

# Home Assistant Dashboard YAML Skill

Card stack for EINHORN's Home. Always apply the constraints below when writing or reviewing dashboard YAML.

## Installed card versions
- **apexcharts-card**: v2.2.3
- **Mushroom**: latest HACS
- **button-card**: latest HACS
- **layout-card**: latest HACS
- **mini-graph-card**: latest HACS
- **auto-entities**: latest HACS
- **Vertical Stack In Card** / **Stack In Card**: latest HACS
- **Timer Bar Card**: latest HACS
- **Advanced Camera Card**: latest HACS
- **Kiosk Mode**: latest HACS

## apexcharts-card v2.2.3 — known constraints

### span / time window
- `span: end: now` — **INVALID** in v2.2.3. Use time unit strings only:
  ```yaml
  span:
    end: day    # ✅ valid
    end: week   # ✅ valid
  # NOT: end: now  ← breaks silently
  ```
- `offset: "-1d"` style offsets are valid for shifting the window

### Annotations (reference lines)
- `annotations:` at the card level is **NOT supported** in v2.2.3 — the schema rejects it as extraneous. Do not use it.
- `borderDash` property is **unreliable** in v2.2.3 — avoid it; use `strokeDashArray` instead if needed

### Full-width cards
- Cards inside a grid must use `grid_options` to span full width:
  ```yaml
  grid_options:
    columns: 12
    rows: auto
  ```
- `columns: 33` or any value above 12 is treated as full-width but may behave unexpectedly — use `12`

### Series config
- `entity:` is required on each series
- `type: line` is the default — omit for cleaner YAML unless changing
- `stroke_width:` not `strokeWidth:`  (YAML convention, not JS)
- `color:` accepts CSS color strings and HA theme variables

## Mushroom cards — constraints

### tap_action / hold_action
```yaml
tap_action:
  action: call-service          # ✅ use call-service (not perform-action)
  service: script.turn_on
  target:
    entity_id: script.my_script
  data:
    variables:
      my_var: value
```
- `action: perform-action` — valid in newer HA but not all Mushroom versions; use `call-service` for safety

### icon_color
Valid named values: `red`, `pink`, `purple`, `deep-purple`, `indigo`, `blue`, `light-blue`, `cyan`, `teal`, `green`, `light-green`, `lime`, `yellow`, `amber`, `orange`, `deep-orange`, `brown`, `grey`, `blue-grey`
- CSS colors do NOT work in `icon_color` — must be one of the above named values

### mushroom-template-card
- `primary:` and `secondary:` accept Jinja2 templates (wrap in `{{ }}` if dynamic)
- `badge_icon:` and `badge_color:` are optional overlay indicators

## button-card — constraints
- `tap_action` uses same call-service syntax as Mushroom
- `styles:` block uses CSS-in-YAML — nest under `card:`, `name:`, `icon:`, etc.
- `variables:` declared in `variables:` block, referenced as `[[variables.my_var]]`

## layout-card — constraints
- `layout: masonry` / `layout: grid` / `layout: horizontal` are the main types
- Grid layout uses `columns:` at the layout level, not per-card
- Cards inside layout-card do NOT need `grid_options` — layout-card manages its own grid

## Grid layout (native Lovelace)
```yaml
type: grid
columns: 3       # number of equal columns
square: false    # allow variable height rows
cards:
  - ...
grid_options:
  columns: 12    # how many of the parent's 12-column grid this card occupies
  rows: auto
```
- `columns:` inside `grid_options` is 1-12 (parent grid columns spanned)
- `columns:` at the grid card level is number of child columns

## Common patterns for this dashboard

### Soil moisture trend card (apexcharts)
```yaml
type: custom:apexcharts-card
graph_span: 7d
span:
  end: day
header:
  show: true
  title: Sugar Rush — 7 Day
series:
  - entity: sensor.gw2000b_sugarrush_pepper
    name: Moisture
    stroke_width: 2
grid_options:
  columns: 12
  rows: auto
```
Note: `annotations:` is NOT supported at the card level in v2.2.3 (schema rejects it). Use chart thresholds via `series[].data_generator` or visual reference lines via the `yaxis:` key inside `apex_config:` instead.

### Quick-tap irrigation button
```yaml
type: custom:mushroom-template-card
primary: 10 min
secondary: Tap to run
icon: mdi:sprinkler
icon_color: green
tap_action:
  action: call-service
  service: script.turn_on
  target:
    entity_id: script.linktap_g2s_run_with_duration
  data:
    variables:
      duration_minutes: 10
```

## Reference files
- Key entity IDs for dashboard use are in CLAUDE.md § "Key entity IDs"