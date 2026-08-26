# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Infrastructure Management — Flynn's Homelab

This workspace runs Claude Code inside a Docker container on **Unraid** (`192.168.1.74`), purpose-built for direct infrastructure management of Flynn Einhorn's homelab: Unraid, UniFi networking, and adjacent Home Assistant systems. (GX55/Proxmox, a former secondary hypervisor, was decommissioned 2026-08-20 — unstable hardware. Unraid is the only hypervisor now. Caddy, a former internal reverse proxy, was decommissioned 2026-08-10 — services are reached by raw IP:port, no `*.lan` namespace.)

## Secret Handling (MANDATORY)

- NEVER cat, grep, printenv, or otherwise dump files that may contain credentials (`.env`, `.mcp.json`, `config.docker.php`, `docker-compose.yml`, `*.conf`). Use `grep -c`, key-names-only (`printenv | cut -d= -f1`), or `sed 's/=.*/=<redacted>/'`.
- When a secret must be read, pipe it directly to the consuming command; never echo it to stdout.
- If a secret is exposed anyway, STOP, tell Flynn immediately, and log the rotation task in Notion before continuing.

## Environment Boundaries

Claude runs headless in this Linux container. Files on Flynn's local macOS machine (`kitty.conf`, iTerm/Ghostty configs, `~/Library`, local clipboard) are NOT reachable. If a task requires a local Mac file, say so immediately and produce a copy-paste block or a script for Flynn to run locally instead of guessing at root causes.

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

## Documentation

### Homelab Documentation Rule

After any change to infrastructure (containers, backups, IPAM, UniFi, Home Assistant, irrigation), update the corresponding Notion page in the same session: what changed, why, current values, and rotation/next-action items. Cross-check Notion before proposing changes so we don't re-fix already-resolved items.

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

## This repo's own architecture

This repo *is* the container's Claude Code config (hooks, skills, MCP config) — there's no build/lint/test workflow; changes take effect on the next session/redeploy.

**PreToolUse hook chain** (wired in `.claude/settings.json`): each hook reads the tool-call JSON from stdin and, to block, prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}` and exits 0 (a non-JSON stdout or non-zero exit is not a deny — it's a broken hook). Three independent hooks fire on different matchers:
- `secret-guard.sh` (matcher: `Bash`, `Read`) — thin wrapper that shells out to `secret_guard_check.py` for the actual decision. The Python file exists because an earlier pure-bash/regex version had statement-boundary bugs on multi-line commands and heredocs; the rewrite does heredoc-aware statement splitting and quote-aware tokenizing (`shlex`). It denies reads/greps/cats of secret-bearing files (`.mcp.json`, `settings.local.json`, `secrets.yaml`, `.env`, SSH private keys, etc.) unless the invocation is a narrow, projected extraction (key names only, or via `secret_guard_check.py --redact <path>`), and separately carves out `sed -i` (in-place edits produce no stdout, so the generic content-leak rule doesn't apply — see the `SED_INPLACE_NO_PRINT_RE` comment for the incident that motivated it). `jq` is deliberately not relied on for anything load-bearing — it isn't installed in this container and ad-hoc `apt install`s don't survive redeploys.
- `ha-yaml-check.sh` (matcher: `Write|Edit`) — deterministic subset of the `ha-yaml-linter` skill (deprecated top-level keys, tabs, missing `mode:`); the full semantic/Jinja2 checks live only in the skill, not here.
- `block-ha-overview.sh` (matcher: the HA `ha_get_overview` tool and the `ha_call_{read,write,delete}_tool` proxies) — unconditionally denies `ha_get_overview` because its response embeds the live HA MCP token in `settings_url_hint`/`settings_url` regardless of field projection, and a PreToolUse hook can only gate the *input* of a call, not redact the *response*. Also inspects `tool_input.name` on the three proxy tools, since they can invoke `ha_get_overview` under a different top-level tool name that a name-only matcher would miss.

**PostToolUse hook**: `secret-scan-output.sh` (matcher: `Bash`, `Read`) — thin wrapper around `secret_scan_output.py`, a second-line detector that scans every matched tool's *result* for known credential-shape prefixes (AWS/GitHub/Slack/Google/OpenAI/Anthropic keys, JWTs, PEM blocks, Bearer tokens, the HA-MCP `/private_...` URL shape) and generic high-entropy strings. **This cannot redact or undo anything** — by the time it runs, the output already reached the transcript — so it only raises a fast warning (`decision: block` with a `reason`, which surfaces as feedback rather than hiding the prior output) telling Claude to stop, tell Flynn, and log a rotation task via the `rotate` skill. It never prints the matched value itself, only a redacted preview and category, so the warning can't become a second leak. The high-entropy check is deliberately noisy (a mixed-alphanumeric filename or identifier can trip it) — treat a hit as "look at this," not proof of an actual secret.

**Secret Handling guardrails, PreToolUse layer** — the real-incident-driven detail behind the top-level Secret Handling section: `secret_guard_check.py`'s per-statement checks (`check_content_leak`, `ends_in_redirect`, `REDACTED_PIPE_RE`) are token-aware (shlex-based), not raw string-tail regexes, after a 2026-08-26 incident where a `python3 -c` one-liner printed `.mcp.json`'s embedded HA MCP secret: the piped `sed` "redaction" only matched `Bearer`/`token`-prefixed text (missed the actual `/private_XXXX` URL-path shape), and the hook's own `REDACTED_PIPE_RE`/`ends_in_redirect` both waved it through — one by trusting the literal word "redacted" appearing anywhere in the command, the other by misreading the literal `>` inside `<redacted>` as a real shell redirect. Ad-hoc sed/awk "redaction" of a sensitive-path statement is no longer trusted at all; only the tested `--redact` tool, a real file redirect, or genuine keys-only extraction are accepted.

**Red-green-refactor for bug fixes in this repo**: since this repo has no build/lint/test workflow of its own (hooks/skills, not an application), "tests" here mean a reproduction script demonstrating the bug against `secret_guard_check.py`'s functions directly (see the pattern used to find/fix the above incident: a small script importing the module and asserting on `check_content_leak`/`ends_in_redirect` outputs for both the failing case and known-safe cases, run via `python3 script.py > outfile` so the PreToolUse hook's own redirect carve-out applies cleanly). Before declaring a hook fix done: (1) write the failing case first and show it failing, (2) fix the code, (3) re-run that case plus the existing known-safe cases (self-`--redact` invoke, real redirects, `docker inspect | cut -d= -f1`, `grep -oE` key-names-only) so a fix doesn't regress an already-working carve-out, (4) only then report done.

**Skills** (`.claude/skills/*/SKILL.md`) encode HA/UniFi domain procedures the hooks can't (or shouldn't) enforce mechanically — e.g. `ha-yaml-linter` (full lint ruleset), `ha-dashboard-yaml` (pinned card-stack versions/syntax), `ha-audit` (phased audit workflow), `crowdsec-bouncer` (two distinct, unrelated root causes for the same symptom — diagnose before fixing), `scrub` (secret/PII redaction for anything about to leave this workspace).

**Repo quirks worth knowing before touching the tree**: `sav1522_filled_matured_bonds.pdf` and `savings_bonds_inventory.csv` are personal files unrelated to this config, gitignored, not part of "the codebase." `$LOGDIR/` is a stray directory from a shell variable-expansion bug (literal `$LOGDIR`, unexpanded), also gitignored. `.claude/hooks/secretguardhooks.zip` is an externally-proposed hook bundle that was reviewed and declined — not live, kept for reference.

## `scripts/`

Repeatable, read-only-first homelab scripts distilled out of ad-hoc session work, so setup/check steps don't get rediscovered from transcripts each time. All read secrets from env vars only (never hardcoded), support `--dry-run`, and log each step with a timestamp.

- `homelab-audit.sh` — data-collection sweep backing the `homelab-audit` skill: Docker container states (flags `Exited`/`Created`), recent per-container error-log hit counts, and (if `HA_URL`/`HA_TOKEN` are set) Home Assistant unavailable entities. Run it before classifying findings as BROKEN/NORMAL/ALREADY-RESOLVED against Notion — it does not touch Notion itself. Usage: `scripts/homelab-audit.sh [--dry-run] [--since 30m] [--log-file PATH]`.

**When to add a new script here:** if a session's diagnosis/setup work runs ~20+ ad-hoc shell commands to establish a repeatable procedure (not a one-off fix), distill it into `scripts/<task>.sh` before the session ends — env-var secrets only, `--dry-run` support, timestamped step logging — and commit it. Otherwise the procedure only exists in that session's transcript and gets rediscovered from scratch next time.

## Working Style

### Response Length

Keep responses under ~400 output tokens. For long audits, backup reports, or config dumps, write the full detail to a file or a Notion page and reply with a short summary plus the link.

### Background Agents

Do not launch background/code-review agents that can edit or push under Flynn's git identity. If parallel work is genuinely needed, ask first and scope the agent to read-only exploration.
