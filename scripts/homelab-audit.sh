#!/bin/bash
# homelab-audit.sh — read-only data-collection sweep for the homelab-audit skill
#
# Collects live evidence (container states, recent error-log hits, HA unavailable
# entities) so findings can be classified BROKEN / NORMAL / ALREADY-RESOLVED
# against the Notion runbook. Does not read or write any Notion state itself —
# that step stays manual/MCP-driven, per .claude/skills/homelab-audit/SKILL.md.
#
# Usage:
#   scripts/homelab-audit.sh [--dry-run] [--since 30m] [--log-file PATH]
#
# Env vars (all optional; secrets are never accepted as flags):
#   HA_URL    — Home Assistant base URL, e.g. http://192.168.1.xx:8123
#   HA_TOKEN  — HA long-lived access token (skips the HA section if unset)
#
# Requires: docker CLI reachable (docker.sock mount), curl for the HA section.

set -euo pipefail

DRY_RUN=false
SINCE="30m"
LOG_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --since) SINCE="$2"; shift 2 ;;
        --log-file) LOG_FILE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

log() {
    local line
    line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
    echo "$line"
    if [ -n "$LOG_FILE" ]; then
        echo "$line" >> "$LOG_FILE"
    fi
}

run() {
    if $DRY_RUN; then
        log "[dry-run] would run: $*"
    else
        "$@"
    fi
}

log "=== Homelab audit sweep starting (since=${SINCE}, dry_run=${DRY_RUN}) ==="

# --- 1. Docker container states -------------------------------------------
log "--- Container states ---"
if $DRY_RUN; then
    log "[dry-run] would run: docker ps -a --format '{{.Names}}\t{{.Status}}'"
else
    docker ps -a --format '{{.Names}}\t{{.Status}}' | sort | while read -r line; do
        log "$line"
    done
fi

# Flag containers that are Exited or stuck in Created (never started) — these
# are the ones worth cross-checking against Notion before assuming a fault.
log "--- Containers needing a closer look (Exited / Created) ---"
if ! $DRY_RUN; then
    docker ps -a --format '{{.Names}}\t{{.Status}}' \
        | awk -F'\t' '$2 ~ /^(Exited|Created)/' \
        | while read -r line; do log "FLAG: $line"; done
fi

# --- 2. Recent error-log sweep ---------------------------------------------
log "--- Error-log hits per running container (since ${SINCE}) ---"
if ! $DRY_RUN; then
    for c in $(docker ps --format '{{.Names}}'); do
        count=$(docker logs --since "$SINCE" "$c" 2>&1 | grep -icE 'error|fatal|panic|traceback|exception' || true)
        if [ "$count" -gt 0 ]; then
            log "FLAG: $c: $count error-level log lines in last ${SINCE}"
        fi
    done
fi

# --- 3. Home Assistant unavailable entities (optional) ---------------------
log "--- Home Assistant unavailable entities ---"
if [ -z "${HA_URL:-}" ] || [ -z "${HA_TOKEN:-}" ]; then
    log "Skipped: HA_URL / HA_TOKEN not set in environment."
else
    if $DRY_RUN; then
        log "[dry-run] would run: curl -s -H \"Authorization: Bearer \$HA_TOKEN\" \"\$HA_URL/api/states\""
    else
        curl -s -H "Authorization: Bearer ${HA_TOKEN}" "${HA_URL}/api/states" \
            | python3 -c '
import json, sys
states = json.load(sys.stdin)
unavail = [s["entity_id"] for s in states if s.get("state") == "unavailable"]
print(f"{len(unavail)} unavailable entities:")
for e in unavail:
    print(f"  {e}")
'
    fi
fi

log "=== Sweep complete ==="
log "Next step (manual/MCP): cross-check FLAG lines above against the Notion runbook before proposing any fix."
