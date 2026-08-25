---
name: ha-yaml-linter
description: Validate and lint Home Assistant YAML before handing it to the user. Use this skill any time you are writing, editing, or reviewing Home Assistant automations, scripts, templates, sensors, or any configuration YAML. Also use when the user pastes HA YAML and asks what is wrong with it, why it is unavailable, or why it is not working. Triggers on: automation YAML, script YAML, configuration.yaml edits, template sensor definitions, Lovelace dashboard YAML, or any mention of 'unavailable', 'deprecated syntax', or 'HA config error'.
---

# Home Assistant YAML Linter

Before delivering any HA YAML, run every check in this skill silently and fix issues before output. Report only issues you found and fixed, or issues that require user input to resolve.

## Required checks — run on ALL HA YAML

### 1. Deprecated syntax
- `service:` at the action level → must be `action:`  (breaking since HA 2024.8)
- `trigger:` (singular, top-level list item) → must be `triggers:` (breaking since HA 2024.10)
- `condition:` (singular, top-level list item) → must be `conditions:`
- `action:` (singular, top-level list item) → must be `actions:`
- `platform: state` with `entity_id:` as a bare string inside a trigger → wrap in a list
- `entity_id:` as a bare string in `target:` → always valid, but flag if mixed with list syntax inconsistently

### 2. Entity ID format
- Must match pattern: `domain.slug` where slug is lowercase, underscores only, no spaces
- Flag any entity ID that contains a capital letter, space, or special character other than `_`
- Flag entity IDs that look like friendly names (e.g. `switch.My Lamp`) — these will silently fail

### 3. Template syntax
- Jinja2 `{{ }}` for expressions, `{% %}` for control flow — flag if reversed
- `| float` without a default → should be `| float(0)` to avoid unavailable errors
- `| int` without a default → should be `| int(0)`
- `states('entity')` vs `state_attr('entity', 'attr')` — flag if attribute access looks wrong
- `is_state()` preferred over `== 'on'` string comparisons for state checks
- `as_timestamp()` on a state value that might be `unavailable` needs a `default` guard

### 4. Mode field
- Scripts and automations must declare `mode:`. Valid values: `single`, `parallel`, `queued`, `restart`
- If omitted, HA defaults to `single` — add it explicitly to be clear

### 5. Unique IDs
- Template sensors and history_stats sensors should have `unique_id:` set
- Flag if `unique_id:` is missing from a sensor that will be registered in the entity registry

### 6. Time format
- Duration strings for timed services must be `HH:MM:SS`
- Flag bare integer seconds passed where a duration string is required

### 7. Indentation and structure
- YAML must use 2-space indentation consistently (HA convention)
- Flag tabs (HA YAML does not allow tabs)
- `sequence:` in scripts must be a list (`- action:`, not `action:` directly)
- `conditions:` must be a list even for a single condition

## Automation-specific checks

- Every trigger should have an `id:` if the automation uses `trigger.id` in actions/conditions
- `numeric_state` triggers need either `above:` or `below:` (or both) — not neither
- `for:` on triggers must be in `HH:MM:SS` format, not bare seconds
- `platform: time_pattern` with `minutes: "/X"` — X must divide evenly into 60

## Script-specific checks

- Scripts that accept variables must declare them in a `fields:` block
- `variables:` block must come before any `action:` steps that use those variables
- Condition steps inside a sequence use `condition:` key, not `conditions:`

## Template sensor checks

- Trigger-based sensors (`- trigger:` block) need both `trigger:` and `sensor:` keys at the same indent level
- State-based template sensors use `- sensor:` directly under `template:`
- `availability:` template should return a boolean, not a string

## After checking

1. Fix all auto-fixable issues silently (deprecated syntax, missing defaults, missing mode)
2. List each fix made with: `✅ Fixed: [what was changed and why]`
3. List any issues that require user input: `⚠️ Needs confirmation: [issue] — [options]`
4. If no issues found, say nothing — just output the YAML

## Known quirks for this instance (EINHORN's Home)

- Target HA version: 2026.7.3 (confirmed live 2026-07-23) — all 2024.8+ deprecations are breaking
- Entity IDs use underscores and snake_case — flag camelCase
- Notify target for push: `notify.mobile_app_iphone_max`
- Removed integrations (do not reference): Smart Irrigation (`sensor.smart_irrigation_peppers`), Irrigation Unlimited (`binary_sensor.irrigation_unlimited_c1_z1`) — both removed 2026-05-18
- Weather entity for forecasts: `weather.weather_com` — `weather.wake_forest` (NWS) is broken for daily forecasts