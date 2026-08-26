---
name: rotate
description: Standardized credential-rotation workflow for this homelab. Use whenever a credential is confirmed or suspected leaked (transcript exposure, secret-guard hook near-miss, routine rotation request), or the user says "rotate <service>". Turns rotation into a repeatable, logged procedure instead of an improvised scramble. Triggers on 'rotate', 'rotate credential', 'rotate key', 'rotate token', 'credential leaked', 'secret exposed'.
---

# Credential Rotation

Input: a **service name** (e.g. `home-assistant`, `unifi`, `unraid`, `frigate`, `openai`, `phpipam`).

This skill never prints a secret value to the transcript at any step. Every
step below must go through `secret_guard_check.py --redact` or a key-name-only
extraction, per [[feedback_homelab_credential_handling]] / CLAUDE.md's Secret
Handling section — the hooks will block content dumps anyway, but don't rely
on the hook as the only defense; write commands that never emit the value in
the first place.

## Steps

### 1. Locate every reference to the credential

Search, without printing values:
- `.mcp.json`, `.claude/settings.local.json` — via key-names-only extraction (`python3 -c "import json;print(list(json.load(open(p)).keys()))"` style, or `secret_guard_check.py --redact <path>`).
- Docker Compose / container env — `docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}'` piped through a redactor that strips values after `=` for any key matching the service, or just list key NAMES (`cut -d= -f1`).
- Config files on the Unraid host relevant to the service (e.g. HA's `secrets.yaml` is never read directly — see below).
- Any `.env` files — key names only.
- This workspace's memory files (`grep -l` for the service name — memory files should never contain raw secrets, but verify).

Produce a plain list: `file:line — key name` for every hit. No values.

### 2. Generate service-specific rotation steps

Each service rotates differently — don't apply a generic template blindly:

| Service | Rotation mechanism |
|---|---|
| Home Assistant | Profile → Security → Long-Lived Access Tokens: revoke the old token, create a new one. HA has no "regenerate in place" — old token is immediately invalid on delete. |
| UniFi (OS Server API key) | Controller UI → Admins → API keys (or the `unifi_mcp` dedicated local admin's key) → revoke + reissue. Confirm the dedicated-account rule ([[feedback_homelab_safety_rules]]) still holds — don't fall back to a shared account. |
| Unraid API key | Unraid webGUI → Settings → Management Access / API key section → reissue. |
| Frigate camera password | Camera's own admin UI (or NVR-adjacent config) → change password → update Frigate's RTSP connection string. |
| OpenAI | platform.openai.com → API keys → revoke old, create new. |
| phpIPAM (`IPAM_DATABASE_PASS` / `PHPIPAM_APP_CODE`) | Per [[project_phpipam_infrastructure]] — MariaDB user password change via socket auth, then `config.php` patch (not full recreate) unless the memory notes say otherwise. |

If the service isn't in this table, ask the user for the rotation mechanism rather than guessing — never invent a rotation flow for a system this container doesn't have documented access to.

### 3. Confirm before rotating

Rotating a live credential is a hard-to-reverse, shared-system action — **stop and get explicit user confirmation before actually invalidating the old credential**, especially if this container's own MCP/API access depends on it (e.g. rotating the HA MCP token may cut this session's own `mcp__homeassistant__*` tool access until reconfigured). State plainly what will break and until when.

### 4. Update references to env-var lookups

For every file found in step 1 that hardcodes the value (rather than reading
from an env var), edit it to reference an environment variable instead
(`${SERVICE_TOKEN}` / `os.environ["SERVICE_TOKEN"]` style, matching the
file's existing convention). Never type the new secret value into the Edit
call itself — write the new value only into the actual secret store (env
file, container env, secrets manager) via a command that doesn't echo it,
then point config files at the variable name.

### 5. Log the rotation in Notion

Search Notion (`notion-search`) for the workspace's credentials/rotation log page — check [[reference_notion_homelab_hub]] first; if no dedicated page is known, ask the user rather than guessing a page ID. Append a dated entry:

```
## YYYY-MM-DD — <service> rotated
- Reason: <leak / routine / incident>
- Old credential: revoked <time>
- New credential: issued, propagated to <list of files/containers updated>
- Verified: <how you confirmed the new credential works>
```

## After rotating

Verify the new credential actually works (a narrow, read-only test call) before declaring done. If anything still references the old value, that's a rotation left incomplete — go back to step 1's file list and finish it.
