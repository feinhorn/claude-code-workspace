---
name: crowdsec-bouncer
description: Diagnose and fix cs-unifi-bouncer causes of unifi_network_cs_unifi_bouncer_* ghost switch entities multiplying in HA (firewall-policy switch churn), and separately, cs-unifi-bouncer crash-loop / 401 LoginRequired restart issues. Use when the user mentions CrowdSec, cs-unifi-bouncer, bouncer crash loop, UniFi 401 LoginRequired, or when a HA audit finds a large/growing number of unavailable switch.unifi_network_cs_unifi_bouncer_* entities. Triggers on: 'crowdsec', 'bouncer', 'cs-unifi-bouncer', 'bouncer restarting', 'firewall policy switches', 'unifi ghost entities'.
---

# CrowdSec / cs-unifi-bouncer — HA Ghost Entity Churn & Crash-Loop

**There are two distinct, unrelated root causes documented here — diagnose which is active before applying either fix.** A 2026-07-28 session initially assumed a recurrence of the known SSO crash-loop (Cause B) and had to rule it out before finding the real driver that day (Cause A). Don't assume either story applies without checking current state first.

## Why this shows up in a Home Assistant audit

The `unifi` HA integration auto-creates a `switch` entity for every firewall policy on the UniFi controller (`unique_id: firewall_policy-<id>`). Whenever `cs-unifi-bouncer` rewrites its managed firewall groups/policies with a **fresh rule ID** (whether from a crash-restart or a routine sync cycle — see below), HA never reuses the old entity: it mints a new one and strands the previous one as an `unavailable`/`restored: true` ghost. A cluster of the same policy name suffixed `_2`, `_3` ... `_17` in HA's entity registry is a direct recreation-count fingerprint — e.g. `_17` means that rule slot was recreated at least 18 times since the last purge.

**This is not a fix on the HA side.** Purging the ghost entities (via `ha_remove_entity`) is just cleanup — it does not stop new ones from being created. The actual fix is on the UniFi controller / Unraid side, described below.

## Diagnosis — run this first, every time

```bash
# 1. Is it actively crash-looping right now? Look for 401 LoginRequired / fatal errors.
docker logs cs-unifi-bouncer --tail 200

# 2. When did it last stop, and why? ExitCode 0 = clean stop (not a crash).
docker inspect cs-unifi-bouncer --format 'Created: {{.Created}}  StartedAt: {{.State.StartedAt}}  FinishedAt: {{.State.FinishedAt}}  ExitCode: {{.State.ExitCode}}  Error: {{.State.Error}}'

# 3. Lifetime restart count — compare against container age (Created, above) to judge if it's actually elevated.
docker inspect cs-unifi-bouncer --format '{{.RestartCount}}'

# 4. Current poll interval and reordering config.
docker inspect cs-unifi-bouncer --format '{{json .Config.Env}}' | tr ',' '\n' | grep -E 'CROWDSEC_UPDATE_INTERVAL|UNIFI_POLICY_REORDERING|UNIFI_MAX_GROUP_SIZE'
```

- Logs show `Firewall group posted` / `Firewall policy posted` bursts with **no errors**, restart count is low relative to container age, `ExitCode: 0` on last stop → **Cause A** (see below). No restart/crash involved.
- Logs show repeating `401 LoginRequired` on the same object ID, restart count climbing fast → **Cause B** (see below).

⚠️ Every `mongosh`/`db.setting.findOne(...)` query against the embedded UniFi controller DB prints the **entire settings document**, including plaintext secrets (`x_ssh_password`, `x_mgmt_key`, `x_api_token`, `x_ssh_sha512passwd`). This has happened at least twice (July 2026 incident, and again 2026-07-28). If you must query this collection, project only the field you need (e.g. `.findOne({_id:...}, {"mgmt.unifi_idp_enabled":1})`) rather than a bare `findOne`, and treat any full-document dump as a credential-rotation trigger for the SSH admin password and mgmt key on the UXG Max.

---

## Cause A (confirmed active 2026-07-28) — poll-interval-driven repost churn, no crash needed

`CROWDSEC_UPDATE_INTERVAL` (env var on the `cs-unifi-bouncer` container) controls how often the bouncer polls CrowdSec's local decision list for changes — **default 5s**, found set to `1m` on this instance as of 2026-07-28. CrowdSec's CAPI community blocklist is a constantly-churning global feed (thousands of participating instances adding/expiring IPs continuously), so on this instance nearly every poll cycle found *some* decision change. Live log evidence (2026-07-28, two cycles exactly 1 minute apart) showed the bouncer responding to even a handful of expired decisions with a full recompute-and-repost: `Number of ipv4 groups needed: N` → `Firewall group posted` → `Firewall policy posted` (×several) → `Starting firewall policy reordering`. This happens via `POST` (create), with no evidence the bouncer diffs against what's already on the UniFi controller before reposting — each such cycle is the likely source of a fresh UniFi firewall-policy rule ID, which is what makes HA mint a brand-new `switch.unifi_network_cs_unifi_bouncer_*` entity and orphan the previous one.

**No restart or crash is required for this** — confirmed 2026-07-28: `ExitCode: 0` (clean stop) and only 47 lifetime restarts over 112 days (container created 2026-04-07) — nowhere near frequent enough to explain ~156 new ghost entities in ~24h. The repost-on-poll-cycle behavior alone accounts for it.

**Fix applied 2026-07-28:** raised `CROWDSEC_UPDATE_INTERVAL` from `1m` to `5m` via Unraid's Docker UI (Docker tab → cs-unifi-bouncer → **Edit** → change env var → **Apply** — must go through the UI, not a raw `docker run`/`docker update`, to preserve the container's other template settings). Trade-off accepted: local-scenario detections (e.g. SSH/HTTP brute force against self-hosted services) now take up to 5 min to get blocked at the firewall instead of ~1 min — acceptable since `cs-unifi-bouncer` is the *only* active bouncer (no host-level firewall bouncer exists per the CrowdSec inventory notes, so this was already the sole enforcement latency floor, just tightened from its own default).

**To verify this fix worked:** re-check `CROWDSEC_UPDATE_INTERVAL` via the diagnosis command above, and watch whether new `switch.unifi_network_cs_unifi_bouncer_*` ghost entities in HA slow down over the following days (`ha_search(domain_filter="switch", state_filter="unavailable")`, filter to `unifi_network_cs_unifi_bouncer`). If churn continues at a similar rate even after the interval change, the "recreate not diff" behavior may be more fundamental than the poll interval alone — worth filing/checking upstream issues at `github.com/Teifun2/cs-unifi-bouncer`.

Relevant `cs-unifi-bouncer` env vars (from upstream README):
| Var | Default | Purpose |
|---|---|---|
| `CROWDSEC_UPDATE_INTERVAL` | `5s` | Poll frequency against CrowdSec's local API |
| `UNIFI_MAX_GROUP_SIZE` | `10000` | Max IPs per UniFi firewall group before splitting into another group |
| `UNIFI_POLICY_REORDERING` | `false` (this instance has it `true`) | Auto-reorder bouncer policies to top priority on every sync |
| `UNIFI_IPV4_START_RULE_INDEX` / `UNIFI_IPV6_START_RULE_INDEX` | `22000` / `27000` | Starting rule index, to avoid colliding with other custom firewall rules |

---

## Cause B (confirmed active again 2026-08-10) — SSO validation crash-loop, 401 LoginRequired

A **separate, recurring** issue (June 2026 first occurrence, July 2026 recurrence, ruled out 2026-07-28, then confirmed active a third time 2026-08-10). Always confirm via Diagnosis above before assuming this is what's happening — don't rely on this file's "last known state" note, since it flips.

### Root cause

`cs-unifi-bouncer` runs as a local admin account on the UniFi controller. The controller setting **"Sync Local Admins with SSO"** (`ace.setting` doc, `key: "mgmt"`, field `unifi_idp_enabled`, site `default`) periodically re-validates local admin sessions — including the bouncer's — against UniFi cloud SSO. With no valid cloud link, that validation fails and invalidates the bouncer's session mid-cycle. The bouncer's own source (`teifun2/cs-unifi-bouncer`, `unifi.go`) has **no re-login/retry logic** — any API error triggers `log.Fatal()`. Docker's `unless-stopped` policy restarts it, it logs in fresh, works for ~20–30 min until the next SSO validation cycle, then repeats. Baseline crash rate is ~2-3/hr when this is active.

**Open mystery (unresolved, now 3 occurrences):** something keeps re-enabling `unifi_idp_enabled` — June 2026, July 2026, and again by 2026-08-10 (found `true`, `RestartCount` had climbed to 70 with a matching ~1/hr crash cadence and a fresh `cs-unifi-bouncer` container `Created` date of 2026-08-08, only ~37h before discovery — worth checking next time whether a container recreation event correlates with the flag flipping back). Possible causes still not confirmed: a controller auto-update resetting settings, or a scheduled config restore. Each fix (setting `false` + restarting both containers) has held for roughly 2-6 weeks before recurring — treat this as an ongoing intermittent issue, not a one-time incident.

**2026-08-22 note:** a `"CrowdSec API connection failed (check API key and URL)"` error burst occurred 2026-08-22 ~02:xx–03:09 EDT (matches this cause's signature), ending in a clean self-restart at 03:10 EDT (`RestartCount` 30) with no recurrence in the 9+ hours since. Could not verify `unifi_idp_enabled` this time — see the stale-access-path note in the Fix section below. The controller migration to a VM (see Reference IDs) happened 2026-08-18, shortly before this occurrence, so it's plausible the migration itself is what reset the flag — worth checking first next time this recurs.

### Fix — STALE as of 2026-08-22, needs a new access path

**The mongosh commands below no longer work.** They targeted `unifi-controller-reborn`, the classic self-hosted UniFi controller *container* at `192.168.1.55:8443`. That controller was fully decommissioned 2026-08-18 (container removed, stale CA templates removed) and replaced by a **UniFi OS Server VM** at `192.168.1.58:11443`. There is no `docker run --network container:<name>` trick against a VM — that only works for sharing a container's network namespace. As of 2026-08-22 there is no confirmed replacement method for reading/writing `unifi_idp_enabled` on the new controller; the public Integration API (`/proxy/network/integration/v1/sites/{site}/...`, `X-API-KEY` auth) is not known to expose this internal `ace.setting`/`mgmt` field. Treat Cause B's diagnosis and fix as **unverified/blocked** until a new access path is found — don't assume the commands below still apply.

Historical commands (proven three times against the old controller — June 2026, July 2026, August 2026 — kept for reference only, **do not run as-is**):

```bash
# STALE — unifi-controller-reborn no longer exists, do not run
docker run --rm --network container:unifi-controller-reborn mongo:8.0 mongosh --port 27117 ace --eval 'db.setting.findOne({_id: ObjectId("5d6d8b0c32d68f04a696a7ec")}, {"mgmt.unifi_idp_enabled": 1})'
```

If `unifi_idp_enabled` is `true`, set it back to `false`:

```bash
# STALE — unifi-controller-reborn no longer exists, do not run
docker run --rm --network container:unifi-controller-reborn mongo:8.0 mongosh --port 27117 ace --eval 'db.setting.updateOne({_id: ObjectId("5d6d8b0c32d68f04a696a7ec")}, {$set: {"mgmt.unifi_idp_enabled": false}})'
```

Then restart both containers for a clean session:

```bash
# unifi-controller-reborn no longer exists — this VM is not a docker container, restart it via Unraid/hypervisor VM controls instead
docker restart cs-unifi-bouncer
```

Bouncer should resume normal CrowdSec→firewall sync immediately with no further 401s — but the `unifi_idp_enabled` check/reset step above needs a new method first.

### Monitoring already in place

`CS_Unifi_Bouncer_Watchdog` — Unraid User Script, runs every 15 min (`*/15 * * * *`), tracks `docker inspect --format RestartCount` for `cs-unifi-bouncer`. Logs to `/var/log/cs_unifi_bouncer_watchdog/watchdog.log` (rotated at 5MB, 3 kept). Alerts via Unraid's native notify **only** when: the container is down and didn't self-recover, a fatal error appears that doesn't match the known `LoginRequired` signature, or restart rate exceeds ~6/hr (above the known ~2-3/hr baseline). Routine self-healing restarts at baseline rate are logged but intentionally do **not** page — so a silent recurrence can sit at "expected" baseline noise without alerting. Check the log directly rather than assuming "no alert" means "not happening." Note this watchdog only catches Cause B's crash pattern — it has no visibility into Cause A's repost churn, since that never crashes or restarts the container.

### Reference IDs

| Item | Value |
|---|---|
| Controller | **UniFi OS Server VM**, `192.168.1.58:11443` — not a docker container, no network-namespace sharing trick available. Replaced `unifi-controller-reborn` (`192.168.1.55:8443`, decommissioned 2026-08-18). |
| CrowdSec container | `crowdsec` (`192.168.1.27`, macvlan `br0`) |
| Bouncer target | UniFi controller `192.168.1.58:11443` (matches current `UNIFI_HOST` env var on `cs-unifi-bouncer`, confirmed 2026-08-22) |
| Site "default" (Wake Forest) site_id | `5d6d8b0732d68f04a696a7e3` |
| Site "super" (decoy) site_id | `5d6d8b0732d68f04a696a7e2` |
| SSO sync setting doc `_id` | `5d6d8b0c32d68f04a696a7ec` (`key: "mgmt"`, field `unifi_idp_enabled`) — access path to read/write this on the new VM controller is unresolved as of 2026-08-22 |
| crowdsec-bouncer admin_id | `6967ca57b390bc250a30db55` |
| Embedded mongod access | STALE — `docker run --rm --network container:unifi-controller-reborn ...` no longer works, controller is now a VM not a container |

---

## Access note for Claude Code sessions

Fixing either cause requires Docker/SSH access to the Unraid host — **not available from the HA MCP toolset** (`ha_mcp_tools` intentionally excludes `shell_command`/`command_line`, and there is no Unraid/Docker MCP server configured as of 2026-07-28). A Claude Code session working from `/homeassistant` cannot execute the commands above directly — hand them to the user to run and interpret the output they paste back, or use a session/tool with actual Unraid shell access.

## Related Notion pages (canonical detail — check these first, this skill is a summary)

- 🔐 UniFi Access Lockout & Bouncer Crash Loop — July 2026 (`39e12807-f3a2-81f9-b1a6-c74b16c2bb0a`) — Cause B's most recent full incident writeup, includes the plaintext-secrets-in-transcript finding referenced in the Diagnosis warning above.
- 🛡️ crowdsec (`95d72763-fa85-4993-8920-df60cc556061`) — main CrowdSec instance inventory (collections, acquis, bouncers, known issues incl. "no host firewall bouncer")
- 🔄 CrowdSec Setup — Session Handoff (June 11 2026) (`37c12807-f3a2-818c-b010-e541986d6711`) — general `cscli` command reference
- Media Stack Health Check — June 2026 (`37b12807-f3a2-81df-81cd-ee97e0feac0c`) — the original June occurrence of Cause B
