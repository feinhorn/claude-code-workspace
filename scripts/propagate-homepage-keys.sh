#!/bin/bash
# propagate-homepage-keys.sh — after rotate-homepage-keys.sh, push the new
# sabnzbd / sonarr / radarr API keys into the downstream consumers that still
# hold the old ones:
#
#   sonarr.db   <- new sabnzbd key   (DownloadClients row)
#   radarr.db   <- new sabnzbd key
#   prowlarr.db <- new sonarr + radarr keys   (Applications rows)
#   bazarr  config.yaml   <- new sonarr + radarr keys
#   seerr   settings.json <- new sonarr + radarr keys
#
# Method: each consumer is stopped, then an exact `old-key -> new-key` string
# replacement is done in its config/db, then it's restarted. The keys are
# unique 32-char hex strings and old/new are the same length, so the swap is
# precise and (for the SQLite DBs) byte-length-safe. Old keys are read from the
# `.bak.<stamp>` files rotate-homepage-keys.sh left; new keys from its 0600 env
# file. Neither value is ever printed.
#
# Consumers whose only copy of a rotated key is Homepage's services.yaml
# (prowlarr, bazarr, tautulli, gluetun own keys) are handled by Phase B, not here.
# Notifiarr stores its *arr keys server-side (notifiarr.com), nothing local to change.
#
# Usage:
#   scripts/propagate-homepage-keys.sh --dry-run [--env-file PATH]
#   scripts/propagate-homepage-keys.sh          [--env-file PATH]
#
# Must run on the Unraid host. Requires: docker, grep, sed, awk.

set -euo pipefail

DRY_RUN=false
ENV_FILE="/root/homepage-secrets.$(date -u +%Y%m%d).env"
LOG_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; shift ;;
        --env-file) ENV_FILE="$2"; shift 2 ;;
        --log-file) LOG_FILE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

log() {
    local line; line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
    echo "$line"; [ -n "$LOG_FILE" ] && echo "$line" >> "$LOG_FILE"; return 0
}

[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }

# --- new keys (from the rotation run's 0600 env file) ---------------------
newkey() { grep "^HOMEPAGE_VAR_${1}_KEY=" "$ENV_FILE" | head -1 | cut -d= -f2-; }
NEW_SAB="$(newkey SABNZBD)"
NEW_SONARR="$(newkey SONARR)"
NEW_RADARR="$(newkey RADARR)"

# --- old keys (from the newest pre-rotation backup of each service) ------
newest_bak() { ls -t "$1".bak.* 2>/dev/null | head -1; }
OLD_SAB="$(   awk -F'= ' '/^api_key = /{print $2; exit}'      "$(newest_bak /mnt/cache/appdata/binhex-sabnzbdvpn/sabnzbd.ini)")"
OLD_SONARR="$(grep -oE '<ApiKey>[^<]+' "$(newest_bak /mnt/cache/appdata/binhex-sonarr/config.xml)" | sed 's/<ApiKey>//')"
OLD_RADARR="$(grep -oE '<ApiKey>[^<]+' "$(newest_bak /mnt/cache/appdata/binhex-radarr/config.xml)" | sed 's/<ApiKey>//')"

for pair in "SAB:$OLD_SAB:$NEW_SAB" "SONARR:$OLD_SONARR:$NEW_SONARR" "RADARR:$OLD_RADARR:$NEW_RADARR"; do
    IFS=: read -r nm o n <<< "$pair"
    if [ -z "$o" ] || [ -z "$n" ]; then log "ERROR: missing old/new key for $nm — aborting"; exit 1; fi
    if [ "${#o}" != "${#n}" ]; then log "ERROR: $nm old/new key length differs (${#o} vs ${#n}) — unsafe for sqlite, aborting"; exit 1; fi
    if [ "$o" = "$n" ]; then log "ERROR: $nm old == new — env/backup mismatch, aborting"; exit 1; fi
done

# consumer | container | file (blank-sep list) | which keys it holds
CONSUMERS=(
    "sonarr|binhex-sonarr|/mnt/cache/appdata/binhex-sonarr/sonarr.db|SAB"
    "radarr|binhex-radarr|/mnt/cache/appdata/binhex-radarr/radarr.db|SAB"
    "prowlarr|prowlarr|/mnt/cache/appdata/prowlarr/prowlarr.db|SONARR RADARR"
    "bazarr|bazarr|/mnt/cache/appdata/bazarr/config/config.yaml|SONARR RADARR"
    "seerr|Seerr|/mnt/user/appdata/seerr/settings.json|SONARR RADARR"
)

pat_for() { case "$1" in SAB) printf '%s' "$OLD_SAB";; SONARR) printf '%s' "$OLD_SONARR";; RADARR) printf '%s' "$OLD_RADARR";; esac; }
new_for() { case "$1" in SAB) printf '%s' "$NEW_SAB";; SONARR) printf '%s' "$NEW_SONARR";; RADARR) printf '%s' "$NEW_RADARR";; esac; }

log "=== propagation (dry_run=${DRY_RUN}, env=${ENV_FILE}) ==="
changed=(); nochange=(); failed=()

for row in "${CONSUMERS[@]}"; do
    IFS='|' read -r name container file keys <<< "$row"
    log "--- $name ($container) ---"
    if [ ! -f "$file" ]; then log "$name: $file missing — SKIP"; failed+=("$name"); continue; fi

    hits=0
    for k in $keys; do
        c=$(grep -c -F "$(pat_for "$k")" "$file" 2>/dev/null || true)
        [ "$c" -gt 0 ] && log "$name: holds OLD $k key ($c occurrence(s))"
        hits=$((hits + c))
    done
    if [ "$hits" -eq 0 ]; then log "$name: no old keys present — nothing to do"; nochange+=("$name"); continue; fi

    if $DRY_RUN; then log "$name: would stop, swap $hits value(s), restart"; continue; fi

    bak="${file}.prop-bak.$(date -u +%Y%m%dT%H%MZ)"
    cp "$file" "$bak"; log "$name: backed up -> $bak"
    docker stop "$container" >/dev/null

    for k in $keys; do
        old="$(pat_for "$k")"; new="$(new_for "$k")"
        # exact fixed-string, equal-length swap; '|' delimiter avoids hex clashes
        sed -i "s|${old}|${new}|g" "$file"
    done

    # every old key must now be gone
    stale=0
    for k in $keys; do
        c=$(grep -c -F "$(pat_for "$k")" "$file" 2>/dev/null || true); stale=$((stale + c))
    done
    if [ "$stale" -ne 0 ]; then
        log "$name: swap left $stale stale value(s) — restoring $bak"
        cp "$bak" "$file"; docker start "$container" >/dev/null; failed+=("$name"); continue
    fi

    docker start "$container" >/dev/null
    log "$name: swapped $hits value(s), restarted"
    changed+=("$name")
done

log "=== done: changed=[${changed[*]:-}] nochange=[${nochange[*]:-}] failed=[${failed[*]:-}] ==="

if [ ${#changed[@]} -gt 0 ] && ! $DRY_RUN; then
cat <<EOF

Post-checks (do in each app's UI once it's back up):
  Sonarr / Radarr : Settings -> Download Clients -> SABnzbd -> Test  (expect OK)
  Prowlarr        : Settings -> Apps -> Sonarr & Radarr -> Test + Sync App Indexers
  Bazarr          : Settings -> Sonarr / Radarr -> "Test" shows green
  Seerr           : Settings -> Services -> Sonarr/Radarr -> "Test" ok
Rollback if needed: restore the matching *.prop-bak.* file and restart the container.
EOF
fi

[ ${#failed[@]} -eq 0 ]
