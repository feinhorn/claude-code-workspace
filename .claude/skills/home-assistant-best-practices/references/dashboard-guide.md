# Dashboard Guide

## Dashboard Structure

```json
{
  "title": "My Home",
  "icon": "mdi:home",
  "config": {
    "views": [
      {
        "title": "Overview",
        "path": "home",
        "type": "sections",
        "max_columns": 4,
        "sections": [
          {"title": "Climate", "cards": [...]},
          {"title": "Lights", "cards": [...]}
        ]
      }
    ]
  }
}
```

**url_path rules:**
- New dashboards must contain a hyphen: `my-dashboard` (not `mydashboard`)
- Use `lovelace` to target the built-in default dashboard
- `dashboard_id`: internal identifier (returned on create, used for update/delete)
- `url_path`: URL identifier (user-facing, used in dashboard URLs)

---

## View Types

| Type | Use for |
|------|---------|
| `sections` | Most dashboards (RECOMMENDED) — grid-based, responsive |
| `panel` | Full-screen single cards (maps, cameras, iframes) |
| `sidebar` | Two-column layouts with primary/secondary content |
| `masonry` | Legacy — auto-arranges cards, less control |

### View Configuration

```json
{
  "title": "View Name",
  "path": "unique-path",
  "type": "sections",
  "icon": "mdi:icon",
  "max_columns": 4,
  "sections": [...],
  "subview": false,
  "badges": ["sensor.entity_id"]
}
```

---

## Built-in Cards

| Category | Cards |
|----------|-------|
| **Modern Primary** | tile, area, button, grid |
| **Container** | vertical-stack, horizontal-stack, grid |
| **Logic** | conditional, entity-filter |
| **Display** | sensor, history-graph, statistics-graph, gauge, energy, calendar, distribution |
| **Legacy Control** | entity, entities, light, thermostat (use tile instead) |

**Default:** Use `tile` card for most entities.

### Tile Card

```json
{
  "type": "tile",
  "entity": "climate.bedroom",
  "name": "Master Bedroom",
  "icon": "mdi:thermostat",
  "features": [
    {"type": "target-temperature"},
    {"type": "climate-hvac-modes", "style": "dropdown"}
  ],
  "tap_action": {"action": "more-info"}
}
```

### Grid Card

```json
{
  "type": "grid",
  "columns": 3,
  "square": false,
  "cards": [
    {"type": "tile", "entity": "light.kitchen"},
    {"type": "tile", "entity": "light.dining"}
  ]
}
```

---

## Features

Quick controls on tile/area/humidifier/thermostat cards.

| Domain | Feature types |
|--------|--------------|
| Climate | `climate-hvac-modes`, `climate-fan-modes`, `climate-preset-modes`, `target-temperature` |
| Light | `light-brightness`, `light-color-temp` |
| Cover | `cover-open-close`, `cover-position`, `cover-tilt` |
| Fan | `fan-speed`, `fan-direction`, `fan-oscillate` |
| Media | `media-player-playback`, `media-player-volume-slider` |
| Valve | `valve-open-close`, `valve-position` |
| Other | `toggle`, `button`, `alarm-modes`, `lock-commands`, `numeric-input`, `datetime-picker` |

Feature `style` options: `"dropdown"` or `"icons"`

---

## Actions

```json
{
  "tap_action": {"action": "toggle"},
  "hold_action": {"action": "more-info"},
  "double_tap_action": {"action": "navigate", "navigation_path": "/lovelace/lights"}
}
```

Action types: `toggle`, `call-service`, `more-info`, `navigate`, `url`, `none`

---

## CSS Styling

### Theme Overrides

```css
:root {
  --primary-color: #03a9f4;
  --ha-card-background: rgba(26, 26, 46, 0.9);
  --ha-card-border-radius: 16px;
}
```

### Card-mod (Per-Card Styling)

Requires `card-mod` HACS component:

```yaml
type: entities
card_mod:
  style: |
    ha-card {
      --ha-card-background: teal;
    }
```

---

## Custom Cards

```javascript
class MyCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this.config = config;
  }
  set hass(hass) {
    if (!this.content) {
      this.innerHTML = `<ha-card header="${this.config.title || 'My Card'}">
        <div class="card-content"></div>
      </ha-card>`;
      this.content = this.querySelector(".card-content");
    }
    const state = hass.states[this.config.entity];
    this.content.innerHTML = state ? `State: ${state.state}` : "Entity not found";
  }
  getCardSize() { return 2; }
}
customElements.define("my-card", MyCard);
```

Usage: `{"type": "custom:my-card", "entity": "sensor.temperature"}`

Register as a dashboard resource via `/api/config/lovelace/resources` with `resource_type: "module"`.

---

## HACS Cards

| Use case | Solution |
|----------|----------|
| Popular community card | HACS |
| Small custom styling | Inline CSS via HA dashboard resource API |
| One-off custom card | Inline module via HA dashboard resource API |

### Popular HACS Cards
- **mushroom** — Modern, clean card collection
- **button-card** — Highly customizable buttons
- **mini-graph-card** — Compact graphs
- **card-mod** — CSS styling for any card
- **layout-card** — Advanced layout control
- **apexcharts-card** — Professional charts

---

## Common Pitfalls

| Issue | Solution |
|-------|----------|
| url_path rejected | New dashboards need a hyphen: `my-dashboard` not `mydashboard`. Use `lovelace` for the default dashboard. |
| Entity not found | Use full entity ID: `light.living_room` not `living_room` |
| Features not working | Match feature type to entity domain |
| Custom card not loading | Check resource type is `module` and verify URL is accessible |

---

## Modern Best Practices (2026+)

- Use **sections** view type with grid-based layouts
- Use **tile** cards as primary card type (replaces legacy entity/light/climate cards)
- Use **grid** cards for multi-column layouts within sections
- Create **multiple views** with navigation paths (avoid single-view endless scrolling)

### Recent Features (2026.2–2026.4)

| Feature | Version | Details |
|---------|---------|---------|
| **Distribution card** | 2026.2 | Proportional horizontal bars across multiple entities |
| **Section background colors** | 2026.4 | Sections support custom `background_color` with opacity |
| **Card favorites** | 2026.4 | Light color/cover position favorites on tile cards |
| **Auto-height cards** | 2026.4 | Cards auto-adjust height based on content |

**Legacy patterns to avoid:**
- Masonry view — use sections for precise control
- Generic "entities" cards — use tile cards
- Single-view dashboards — create multiple views with navigation
