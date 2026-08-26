---
name: homelab-audit
description: Run a broad homelab audit spanning Docker containers on Unraid and Home Assistant entities, cross-checked against Notion so already-resolved items aren't re-flagged. Use when Flynn asks for a general homelab health check, container + HA sweep, or "what's broken across the homelab" (not just HA-only — for HA-only audits use the ha-audit skill). Triggers on 'homelab audit', 'check everything', 'full health check', 'container errors', 'sweep docker and HA'.
---

# Homelab Audit

1. Read the relevant Notion runbook FIRST; list items already marked resolved and skip them.
2. Sweep docker containers for errors (last 24h) and Home Assistant for unavailable/ghost entities.
3. Classify findings: BROKEN / NORMAL / ALREADY-RESOLVED. Only propose fixes for BROKEN.
4. Never dump env files or configs containing secrets; redact by default.
5. Apply approved fixes, then update the Notion page with what changed and any rotation tasks.
6. Reply with a summary under 400 tokens; put full detail in Notion.
