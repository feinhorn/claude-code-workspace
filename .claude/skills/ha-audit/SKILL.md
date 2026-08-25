---
name: ha-audit
description: Run a structured audit of the Home Assistant instance using live MCP data. Use this skill when the user asks to audit HA, check for issues, do a health check, find broken entities, review automations, or asks 'what's wrong with my HA'. Also use proactively when the user reports something is unavailable or not working and wants a broader picture. Triggers on: 'audit', 'health check', 'what's broken', 'check my HA', 'inventory', 'find issues', 'broken entities', 'ghost entities'.
---

# Home Assistant Audit Skill

Structured audit methodology for EINHORN's Home (HA 2026.7.x, MCP-connected via `homeassistant` MCP server).

## Audit workflow

Run these phases in order, using the `mcp__homeassistant__*` tools directly — no file parsing needed, tools return structured JSON.

### Phase 1 — Data collection

Core sweep (run in parallel where independent):
- `ha_get_overview(detail_level="standard", fields=["system_summary","domain_stats","notification_count","notifications","repair_count","repairs","system_info"], include_dismissed_repairs=true)` — entity counts by domain + state breakdown per domain, active repairs, HA version/state in one call.
- `ha_get_integration()` (paginate with `offset` if `has_more`) — every config entry's `state` (`loaded` / `setup_retry` / `not_loaded`) and `source`. `source: "ignore"` + `not_loaded` is a user-declined discovery flow, not a failure — don't flag it.
- `ha_search(domain_filter=<domain>, state_filter="unavailable")` per domain that `domain_stats` shows has unavailable entities — get the actual entity list, not just the count.
- `ha_get_logs(source="system", level="ERROR", hours_back=<window>)` and `ha_get_logs(source="error_log", search=<keyword>, hours_back=<window>)` — system log is pre-grouped/deduplicated with `count`/`first_occurred`, better for scanning; error_log gives raw lines when you need exact timestamps or tracebacks.

Don't trust a hardcoded entity-count baseline from a prior audit — always pull the live count via `ha_get_overview`; the "Reference" section below gives a snapshot only for scale, not for diffing.

### Phase 2 — Triage by severity

| Severity | Color | Criteria |
|----------|-------|----------|
| 🔴 Critical | Red | Unavailable script/automation that was previously working; offline integration affecting safety (irrigation control, security/alarm); a whole subsystem down |
| 🟡 Optimization | Yellow | Deprecated syntax; entity with no area assigned; automation disabled >7 days; `setup_retry` integration not previously known-expected |
| 🔵 Cleanup | Blue | Ghost entities (`unavailable` + `restored: true`); unused scripts; duplicate entities from two integrations covering the same physical device |
| ⚫ Observation | Grey | Offline devices that are expected to be seasonal/optional; known/already-documented `setup_retry` (e.g. `apcupsd` waiting on UPS daemon) |

**Triage rules learned from live incidents (2026-07-23 session) — apply these before concluding root cause:**

1. **`restored: true` + `unavailable`** = integration failed to reconnect after a restart. Don't suggest YAML/config fixes for these — check the integration's connectivity/health first (`ha_get_logs` filtered to the integration's logger name).
2. **A reload/restart that refreshes the entity's `last_changed` timestamp but the state stays `unavailable`** means the reload succeeded at the HA/config-entry level but the entity's underlying data source is still failing — check `ha_get_logs` for the *specific* logger (e.g. `aioamazondevices`, `motionblinds.motion_blinds`) in the minutes right after the reload, not just whether the config entry shows `loaded`.
3. **Partial coordinator failure is common and easy to misdiagnose as "integration is down."** A single failing upstream API call (e.g. Alexa's "communications settings" endpoint) can leave one class of entities (switches) permanently `unavailable` while everything else from the same integration (media_player, motion/temperature sensors, connectivity) works fine. Check `ha_search(... group_by_domain=true)` for the integration's full entity set before concluding the whole thing is broken.
4. **Don't assume entity naming implies platform.** Entities named after a branded device (e.g. "Front Door Motion Detection") are not necessarily served by that brand's native HA integration — always confirm via `ha_get_entity(entity_id)` → `platform` field before diagnosing. A known live example: several "Ring-named" switch/camera entities here were actually a third-party `ring-mqtt` bridge (`platform: mqtt`) duplicating the native `ring` integration's device — two different failure domains for what looks like one device.
5. **Cross-VLAN local-network integrations (UDP discovery/polling, e.g. `motion_blinds`) recur on every HA restart** if the HA host has no local IP on the target device's subnet — look for `"Could not find working interface for <host> ..., using interface 'any'"` in `ha_get_logs`. This is a host-networking gap, not something a config reload fixes; see "Known architecture" below for this instance's specific VLAN layout.

### Phase 3 — Known architecture & recurring issues (update this section as things change — don't let it go stale)

**Network / VLAN topology** (source: Notion "VLAN Segmentation & Firewall Rules" page; firewall model corrected and VLAN 107 fix confirmed resolved 2026-07-24 — see CLAUDE.md, git commit `35fda06`. This section had gone stale on both points for a couple weeks before that correction; re-verify against CLAUDE.md/Notion rather than trusting this file blindly if it's been a while):
- Private LAN / Internal: native VLAN, `192.168.1.0/24` — HA host lives here (`192.168.1.43`), plus Unraid, Plex, NAS, most trusted infra.
- IoT VLAN 107: `192.168.2.0/24` — Ring, Ecobee, Ecowitt, Echo devices, Motionblinds Gateway, IoT AdGuard DNS (`.5`, `.7`).
- Guest/Hotspot VLAN 200: `192.168.3.0/24` — wireless guest clients only.
- **Firewall default posture: default-deny in BOTH directions between Internal and IoT (V2 zone-based policies) — not "Internal→IoT broadly allowed" as this section previously said.** Each needed flow, either direction, requires its own narrow ALLOW pinhole by source/dest IP and port (e.g. `Allow Frigate to Backyard Camera (RTSP)`). Notion flagged the Guest→Internal explicit block as a missing/critical gap as of 2026-08-08 — don't assume Guest VLAN is isolated without checking current policy state.
- **VLAN 107 interface fix: RESOLVED 2026-07-24, not "in progress."** HA's VM second vNIC (`enp5s0` — not `enp4s0`, this section had the wrong interface name too) was repointed to a new Unraid-host-level VLAN 107 bridge, giving the VM a native `192.168.2.81/24` address, confirmed durable across a full VM restart. The `motion_blinds` "Could not find working interface" error stopped recurring after this fix — **one isolated recurrence at 2026-08-10 08:56 was investigated and closed same day, not a regression.** `ip addr` on the HA VM re-confirmed `enp5s0` still holds its native `192.168.2.81/24` address; `ha_get_integration` shows the `motion_blinds` entry as `loaded`; and a 24h log search found zero further occurrences. Most likely a transient timing blip during an HA restart/reload earlier that day (several reloads happened that morning during an unrelated NUT/apcupsd fix session) rather than a network config regression. No action taken; flag again only if it recurs.

**Sunroom Shades system — REMOVED 2026-07-24, do not treat as active.** This section previously described it as "a second primary active system alongside irrigation"; that stopped being true and went uncorrected for a while — caught during the 2026-07-27 full-config audit. The prior sun/heat automation (8 automations, 2 preset scripts, 36 storage helpers, a Sunroom dashboard view) was removed wholesale as too flaky. The 6 Motionblinds covers (`cover.rollerblind_0007`–`000d`, skipping `000b` — only 6 of those 7 hex IDs exist, post-factory-reset remap) and the Motionblinds Gateway integration are untouched and still controlled manually (cover entities or the Bliss app). `docs/sunroom_shades.md` referenced here previously no longer exists (`docs/` is empty) — the Notion "Sunroom Shades — System Architecture" page is the only remaining reference, for historical/removed-design context only. Don't recreate this system assuming prior helpers/scripts/automations still exist; see CLAUDE.md's "Sunroom shades — automation removed" section for the authoritative note.

**Alexa Devices integration — REMOVED, confirmed gone as of the 2026-07-27 audit.** Previously reverse-engineered (`aioamazondevices`) with a known-fragile "communications settings" API call (see git history of this file for the old troubleshooting notes if the integration ever returns). As of 2026-07-27 it's absent from `ha_get_integration()` entirely — not even a stale/`ignore` entry — and a config-body search across automations/scripts/scenes/dashboards for "alexa" and "echo" (media_player domain) found zero orphaned references, so the removal was clean. If Echo/Alexa entities or an `alexa_devices` config entry reappear, that's a re-add, not a leftover — verify with the user before assuming this note is stale again.

**Ring — two integrations can exist for the same device, don't conflate them:**
- Native `ring` integration (`platform: ring`) — cameras (live view, last recording), battery, wifi signal, basic motion-detection/chime switches. Generally reliable.
- Third-party `ring-mqtt` bridge (`platform: mqtt`, via the Mosquitto broker config entry) — richer switches (Event/Live Stream toggles, Snapshot Mode, tunable durations) but runs as a **separate Docker container outside HA** (Unraid). If its entities go `unavailable`, neither a HA restart nor a `ring` integration reload will fix it — the container itself needs restarting. **Removed entirely 2026-07-23** (user chose native-only to eliminate the duplicate-failure-domain risk) — if `platform: mqtt` Ring-branded entities reappear, the bridge container was restarted and re-published its MQTT discovery config; confirm with the user whether that's wanted before re-removing.
- Ring Security/Alarm devices (contact/motion sensors, base station) are a distinct Ring product line from the doorbell/camera line and may need a broader OAuth scope than what's already granted — if newly added devices don't appear after a plain reload, that's the likely reason (needs reauth, not just reload).
- **Push listener crash-loop — first confirmed 2026-08-10, NOT fixed by reload, do not assume a config-entry reload resolves this.** `firebase_messaging.fcmpushclient` repeatedly throws `KeyError: 'id'` from `ring_doorbell/listen/eventlistener.py:323` (`event_id = int(event["ding"]["id"])` — some incoming push payload doesn't nest an `id` under `ding`, likely a newer/different Ring event schema the installed `ring_doorbell` library version doesn't parse). After 3 sequential errors the library logs "Shutting down push receiver due to 3 sequential errors of type ErrorType.NOTIFY" and the listener dies — live push notifications (motion/ding) go silent while the `ring` config entry itself stays `state: loaded` (looks healthy in `ha_get_integration`, so check the actual event entity timestamps, not just entry state). **Reloading the config entry does NOT fix it** — tested 2026-08-10: reloaded twice, and both times the exact same crash-and-shutdown recurred within ~2 seconds of the fresh listener starting, meaning the triggering event(s) are being replayed/re-delivered immediately on reconnect. No HA core update was pending at the time (already on latest, 2026.8.1) and no known upstream GitHub issue was found matching this specific traceback. Detection: `event.front_door_motion` (and the other 5 Ring `event.*` entities) will show a `state` timestamp value frozen far in the past despite `last_updated`/logbook touches around the crash time — that mismatch (state frozen, logbook shows activity) is the signature of this bug, not a real absence of motion. Until an upstream fix lands, there's no known workaround beyond periodic reload (which only restores service until the next malformed event arrives, could be seconds to hours). **2026-08-10: confirmed still actively recurring** (traceback recurred multiple times same day, `event.*` entities still show the frozen-state signature) — pinned version `ring-doorbell==0.9.14` (HA core 2026.8.1, Python 3.14.6). A full bug report was drafted. Target **`home-assistant/core`** (integration bug report, component `ring`), not the upstream `python-ring-doorbell/python-ring-doorbell` library repo directly — confirmed that repo's last push was 2026-02-28 (the commit literally preparing the pinned `0.9.14` release) with 36 issues open since, i.e. effectively unmaintained right now; `home-assistant/core` has an active codeowner (`sdb9696`) on the `ring` integration who gets auto-pinged and is more likely to either patch around it or escalate upstream. Not filed — this environment has no `gh` CLI and no git push credentials, so filing requires the user to paste/submit it themselves.

**Irrigation system** (primary active system, most mature/stable — see main CLAUDE.md for full architecture and current FC/threshold values, which change frequently and should always be re-read fresh rather than cached here):
- Always check: `switch.pepper_timer_d4532236004b1200_water_switch`, `binary_sensor.pepper_timer_d4532236004b1200_is_watering`, all 4 `sensor.gw2000b_*_pepper` moisture readings, `binary_sensor.gw2000b_rain_state_piezo`, `input_boolean.linktap_g2s_irrigation_enabled`, `sensor.peppers_irrigation_max_runtime`.
- `sensor.wake_forest_daily_forecast` must reference `weather.weather_com`, never `weather.wake_forest` (NWS — doesn't support daily forecasts). This was fixed 2026-06-17 and has stayed fixed; only flag if it regresses.

**NUT (Closet UPS) and apcupsd (Unraid UPS) — both FIXED 2026-08-10, no longer `setup_retry`.** Both had the identical root cause: the UPS daemon (`upsd`/`apcupsd`) was bound to `127.0.0.1` only, never exposed to the LAN — not a daemon crash, not a real connectivity gap, just never listening externally. NUT: added `LISTEN 192.168.1.6 3493` to `/etc/nut/upsd.conf` on the AdGuard-Private2 Pi (`192.168.1.6`), restarted `nut-server.service`; also fixed a co-located `nut-monitor.service` (upsmon) crash-loop from a missing `MONITOR` line in `upsmon.conf`. HA-side: the old config entry had been removed to force zeroconf rediscovery; re-added via the HA UI — landed under new entity IDs `sensor.closet_unifi_ups_*` (the old `sensor.closetups_*` prefix is gone, confirmed no orphaned references in any YAML). apcupsd: changed `NISIP 127.0.0.1` → `NISIP 0.0.0.0` in `/etc/apcupsd/apcupsd.conf` on Unraid (`192.168.1.74`), restarted via `/etc/rc.d/rc.apcupsd restart`; entities are `sensor.unraid_*` / `binary_sensor.unraid_online_status`. **Durability risk:** Unraid has the `dynamix.apcupsd` plugin installed (`/boot/config/plugins/dynamix.apcupsd/`), which may regenerate `apcupsd.conf` from its own persisted settings on reboot/plugin update — if `apcupsd` returns to `setup_retry` after a reboot, check the plugin's own NIS bind-address setting via its Unraid GUI page, not just the conf file. Both UPS units now have power-lost/restored/low-battery notifications and dashboard cards — see `packages/ups_monitoring.yaml` and the new "Infrastructure" dashboard view (`dashboard-outdoor/infrastructure`).

### Phase 4 — Report format

```
## 🏠 EINHORN's Home — HA Audit
HA [version] · [date] · [total entity count] entities

### Summary
[2-sentence overview of overall health]

### 🔴 Critical ([count])
[Entity/automation] — [what's wrong] — [paste-ready fix or action]

### 🟡 Optimization ([count])
[item] — [recommendation]

### 🔵 Cleanup ([count])
[item] — [safe to delete / disable]

### ⚫ Observations
[things that are fine but worth noting]

### Paste-ready fixes
[YAML blocks or MCP tool calls for each Critical/Optimization fix, ready to apply]
```

### Phase 5 — Publish to Notion (if requested)

Key Notion pages (confirmed live 2026-07-23):
- Canonical hub: 🤖 AI System Reference — EINHORN's Home (`37d12807-f3a2-81d4-b180-dad5bdf8e103`)
- Device & Integration Inventory: `34a12807-f3a2-815f-b422-e990b6e2c754`
- Deep-detail archive: 📚 AI Reference Archive — EINHORN's Home (`38012807-f3a2-812d-b4a4-cd3561ae3344`)

Use the Notion MCP (`mcp__claude_ai_Notion__notion-fetch` / `notion-search` / `notion-update-page`) to read/update. Verify a page ID still resolves before writing to it — Notion structure has been reorganized more than once this year (Session Memory Capsule pattern rolls into the Archive over time).

## Reference

**Entity count:** re-fetch live via `ha_get_overview` every audit — don't diff against a hardcoded number here, it decays fast (was ~1,464 on 2026-06-17, ~1,375 on 2026-07-23, ~1,690 on 2026-07-27 pre-cleanup / ~1,407 post-cleanup after the 283-entity `unifi` ghost purge that same day; net change reflects real cleanup work and new integrations, not drift, but the absolute number isn't meaningful on its own).

**Integrations active as of 2026-07-27 (55 config entries, re-verify via `ha_get_integration` — don't trust this as current beyond a rough shape check):** sun, hassio, backup, sonos, go2rtc, thread, shopping_list, met, google_translate, radio_browser, synology_dsm, apple_tv, ipp, hacs, dlna_dmr, mobile_app (×2), ha_access_control_manager, adguard (×4), ring, vesync, ecobee (ignored), homekit_controller (×2), samsungtv (×3, ignored), nws, matter, weatherdotcom, ecowitt (×2), reolink (×2), mqtt, frigate, plex, openai_conversation, cpuspeed, fastdotcom, androidtv_remote, cast (ignored), ha_mcp_tools, downloader, analytics, nut (setup_retry), apcupsd (setup_retry), lg_thinq, zha, **roborock** (added since 2026-07-23, undocumented until now — Q Revo vacuum), **unifi** (added since 2026-07-23, undocumented until now — network client tracking + firewall policy state; see the 283-ghost-entity note above). **`alexa_devices` is gone** — present in the 2026-07-23 list, confirmed fully removed by 2026-07-27 (see REMOVED note above).

**Ghost entity cleanup history:** major purge 2026-06-17 (Ring 40, Unraid 92, Plex 7, irrigation legacy 2, stray script 1) and a second pass same day (2 more). 2026-07-27: 283 more from the new `unifi` integration (192 firewall-policy switches, 73 randomized-MAC device_trackers, 18 link-speed sensors — see Phase 3 note). Residual risk: Unraid integration may recreate deleted disk/share/UPS entities on next poll if those volumes/shares still exist; `apcupsd` will recreate UPS entities when the daemon reconnects; `unifi` will recreate new ghost entities the same way every time `cs-unifi-bouncer` restarts or a client rotates its MAC — this is an ongoing pattern, not a one-time cleanup, revisit periodically rather than expecting it to stay at zero.
