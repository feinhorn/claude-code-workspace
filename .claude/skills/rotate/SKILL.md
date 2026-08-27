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

Each service rotates differently — don't apply a generic template blindly. Steps marked **[verified]** come from a completed, Notion-logged rotation and can be followed as written. Steps marked **[confirm live]** are the best known starting point but the exact menu path hasn't been walked end-to-end recently — check the live UI before committing to a specific label, and tighten this section afterward with whatever you actually found (menus drift between versions).

**phpIPAM — `PHPIPAM_APP_CODE`** (the MCP integration's static API app-code) **[verified 2026-08-26]**
1. Log into the phpIPAM web UI (`$PHPIPAM_URL`) as an admin.
2. **Administration → API.**
3. Select the app entry matching this integration's `app_id` (`Claude`, per the AI+MCP subsystem card on the Notion hub) — confirm the name before editing if more than one app is listed.
4. Regenerate/reset that app's code (look for a "Reset" action next to the App code field, or edit the app and clear the code to force regeneration — exact control varies by phpIPAM version).
5. Copy the new code straight into `/root/.claude.json` yourself (the phpIPAM MCP integration is registered via `claude mcp add`, per [[project_phpipam_infrastructure]] — the credential lives there, not in any compose file); don't paste it into any Claude Code tool call.

**phpIPAM — `IPAM_DATABASE_PASS`** (MariaDB `phpipamuser`) **[verified 2026-08-21, see [[project_phpipam_infrastructure]] for full incident notes]**
1. `docker exec -it mariadb mysql -u root` — this image allows passwordless local root via the Unix socket, no `-p`. The documented root password does **not** work.
2. `SELECT User, Host FROM mysql.user WHERE User='phpipamuser';` — check for **more than one host row** (e.g. both `%` and a specific container IP). MariaDB matches the most specific host, so missing one leaves the old password live on that path.
3. `ALTER USER 'phpipamuser'@'<host>' IDENTIFIED BY '<newpass>';` for **every** host row found.
4. Update `IPAM_DATABASE_PASS` on both the `my-phpIPAM-www` and `my-phpIPAM-cron` Unraid containers, recreate both.
5. Re-apply `$api_allow_unsafe = true;` in `/phpipam/config.docker.php` (not `config.php` — that name is wrong, per [[project_phpipam_infrastructure]]) after the `phpIPAM-www` recreate — no native env-var equivalent, gets wiped on every recreate. (`$trust_x_forwarded_headers` is now handled by `IPAM_TRUST_X_FORWARDED=true` and survives recreate on its own — no manual patch needed there anymore.)
6. Back up first if convenient: `docker exec mariadb mysqldump -u phpipamuser -p'<pass>' phpipam > /mnt/user/appdata/phpipam-backups/phpipam-$(date +%Y%m%d).sql`.

**Home Assistant** — two different credentials can both be called "the HA MCP token"; confirm which one before picking a path.
- Core HA Long-Lived Access Token **[confirm live]**: profile (bottom-left avatar) → Security tab → Long-Lived Access Tokens → revoke old → Create Token. No regenerate-in-place — old token dies immediately on delete.
- **HA MCP add-on** (port 9583 — what `/workspace/.mcp.json`'s `homeassistant.url` currently points to, as of 2026-08-26) **[unverified — exact menu path not yet documented]**: check the add-on's own config page (Settings → Add-ons, or Settings → Devices & Services, whichever surfaces it) rather than assuming it matches the core-HA path above. Once walked, record the actual steps here.

**UniFi (OS Server API key)** **[confirm live]**
Controller UI (`https://192.168.1.58:11443`) → the admin/API-key management section (exact current menu label not verified against this UI version) → the dedicated `unifi_mcp`-equivalent account → revoke + reissue. Confirm the dedicated-account rule ([[feedback_homelab_safety_rules]]) still holds — don't fall back to a shared account.

**Unraid API key** **[verified 2026-08-21]**
Unraid webGUI → Settings → Management Access → API Keys (or `unraid-api apikey --overwrite` at the Unraid console) → reissue. Afterward, verify `/boot/config/plugins/dynamix.my.servers/keys/` still has its other key files present — a past rotation once collaterally deleted unrelated ones.

**Frigate camera password** **[verified 2026-08-21]**
Reolink camera's own admin web UI/app at its IP (e.g. `192.168.2.161`) → change the password there first → then update the matching `FRIGATE_<CAM>_PASSWORD` Config field on the Frigate container in the Unraid Docker UI → recreate.

**OpenAI**
platform.openai.com → API keys → revoke old, create new. (Stable, publicly documented UI — not homelab-specific.)

If the service isn't listed here, ask the user for the rotation mechanism rather than guessing — never invent a rotation flow for a system this container doesn't have documented access to.

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
