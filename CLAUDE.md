# Infrastructure Management — Flynn's Homelab

This workspace runs Claude Code inside a Docker container on **Unraid** (`192.168.1.74`), purpose-built for direct infrastructure management of Flynn Einhorn's homelab: Unraid, UniFi networking, and adjacent Home Assistant systems. (GX55/Proxmox, a former secondary hypervisor, was decommissioned 2026-08-20 — unstable hardware. Unraid is the only hypervisor now. Caddy, a former internal reverse proxy, was decommissioned 2026-08-10 — services are reached by raw IP:port, no `*.lan` namespace.)

## Source of truth: Notion

Notion is the canonical source of truth for this homelab, not this file. Primary hub: **"🌐 Homelab / Network"** (workspace: "Flynn Einhorn's Space"). Check Notion before and during infra work — don't rely solely on memory or this file, both can drift out of date.

**Conflict rule:** if Notion's **"🤖 AI System Reference — EINHORN's Home (HA + Unraid)"** page disagrees with this file, **Notion wins**. That page also defines a mandated read order each session: AI System Reference top-to-bottom → Session Memory Capsule → AI Reference Archive (if needed) → re-verify any dated snapshots before trusting them.

Known staleness as of 2026-08-18: the AI System Reference page's UniFi-MCP subsystem card may still reference outdated setup details — verify before trusting any single dated section rather than assuming the whole page is current. As of 2026-08-18, the UniFi controller is a **UniFi OS Server VM at `192.168.1.58:11443`** (migrated off the old self-hosted classic controller at `192.168.1.55:8443`, which has been fully decommissioned — container removed, stale CA templates removed). The `unifi-network` MCP plugin was uninstalled 2026-08-20 (had been non-functional against this new controller — 403 Forbidden on both username/password and API-key auth — since 2026-08-14) — use direct API-key HTTP calls instead.

## Non-negotiable safety rules (from the Notion AI Memory Contract)

- Confirm before: firing an irrigation valve/master switch, restarting Home Assistant, `git push` (never force-push main), deleting entities/automations/scripts/history.
- Never read, expose, or commit `secrets.yaml`.
- Never add `shell_command`/`command_line` to the HA MCP allowlist.
- Never guess entity IDs, YAML, paths, or service names — verify first.
- Never reintroduce a previously-removed integration.
- **New Unraid containers go through Community Applications/templates only** — hand-rolled `docker-compose`/`docker run` is explicitly rejected by house rule (dated 2026-07-27). Note: this container itself was deployed via a hand-rolled Compose stack — a known exception, flagged here for awareness rather than silently repeated.
- Never expose management surfaces to WAN. Never weaken MCP tool allowlists.
- Use dedicated credentials per trust boundary — avoid reusing one account (e.g. `crowdsec-bouncer`) across unrelated integrations where it can be avoided.

## Credential handling (hard-won, repeat incidents)

This homelab has had **multiple confirmed incidents** of plaintext secrets (SSH admin password, mgmt keys, API tokens) leaking into Claude session transcripts — via typing credentials directly into shell commands, and via broad/unprojected MongoDB queries against UniFi's embedded DB (`db.setting.findOne(...)` without a projection). Rules going forward:
- Never type a password/API key directly into a Bash command, Edit call, or any other tool-call argument — those are visible in the transcript. Read/write credentials programmatically (e.g. a script that reads a config file into env vars) so the literal secret never appears in a tool call.
- When querying UniFi's embedded MongoDB, always use a **projected** query for the specific field needed, never a full-document dump.
- Treat any confirmed secret exposure as needing rotation — don't assume "nothing used it" is enough.

## Infrastructure map

| Host | Role | IP | Notes |
|---|---|---|---|
| Unraid | Primary (and only) hypervisor/NAS/Docker host | `192.168.1.74` | Unraid OS 7.3.2, kernel 6.18.38-Unraid. ~40 containers. |
| UXG Max | Core router/firewall | `192.168.1.1` | UniFi gateway. |
| UniFi Network Application | UniFi OS Server (VM), site `8a3bp31m` ("Wake Forest") | `192.168.1.58:11443` | API-key auth. The `unifi-network` MCP plugin was uninstalled 2026-08-20 (403'd against this server on both username/password and API-key paths) — use direct API-key HTTP calls (`X-API-KEY` header) against `/proxy/network/integration/v1/sites/{site}/...` instead. Old classic controller (`unifi-controller-reborn`, `192.168.1.55:8443`) fully decommissioned 2026-08-18. |

VLANs: Private/1 (`192.168.1.0/24`), IoT/107 (`192.168.2.0/24`), Guest/200 (`192.168.3.0/24`). Zone-based firewall, default-deny between Internal↔IoT except named pinholes.

**Migration status:** the Unraid→GX55 migration is over — GX55 was decommissioned 2026-08-20. `kms`/`kms-gui` and `cs-unifi-bouncer` moved back to Unraid; Termix was not restored (replaced by iTerm2 locally). CrowdSec itself stayed on Unraid throughout.

## This container's own capabilities

Deployed via Docker Compose (Unraid Compose Manager plugin), project file at `/mnt/cache/appdata/compose.manager/projects/claude-code/compose.yaml` on the Unraid host. Config/session state persists across redeploys via the `claude-code-config` and `claude-code-ssh` named volumes.

- **Docker control** — `/var/run/docker.sock` mounted; `docker` CLI manages every container on the Unraid host directly.
- **Host shell** — SSH key-auth to `root@192.168.1.74` (key lives on the `claude-code-ssh` volume, persists across redeploys).
- **Unraid API** — `UNRAID_API_KEY` env var, GraphQL endpoint `https://192.168.1.74/graphql`, ADMIN role.
- **Network** — own macvlan IP on `br0` (`192.168.1.51` at time of writing) — a real LAN citizen, not NAT'd behind the host.
- **UniFi API** — direct API-key HTTP calls against the UniFi OS Server at `192.168.1.58:11443`, using a dedicated `unifi_mcp` local admin account (separate credential from `cs-unifi-bouncer`'s, per credential-per-trust-boundary). The `unifi-network` MCP plugin was uninstalled 2026-08-20 — it returned 403 Forbidden against this server on every auth path tried.
- **Notion** (`claude.ai Notion` connector + `notion` plugin skills/commands) — full read/write access to Flynn's Notion workspace.

Given the combination of docker.sock + root SSH + Unraid API key, this container has effectively full control of the Unraid host — treat actions here with the same care as being logged into the host directly.
