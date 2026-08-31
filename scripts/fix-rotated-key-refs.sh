#!/bin/bash
# fix-rotated-key-refs.sh — generalised propagation. Given the sweep file that
# lists every config file still holding a pre-rotation (OLD) key, swap each OLD
# key for its NEW value in place, grouping edits by owning container so each is
# stopped once, all its files fixed, then restarted.
#
# This is the catch-all for consumers not covered by propagate-homepage-keys.sh
# (Kometa, Plexcache-D, Profilarr, Notifiarr, Trailarr, Unmanic, and the
# Prowlarr-synced-indexer apiKey inside sonarr.db / radarr.db, …).
#
# Method is the same exact equal-length old->new string replace while the
# container is stopped — byte-safe for SQLite. Old keys from the newest
# *.bak.<stamp>* rotate-homepage-keys.sh left; new keys from its 0600 env file.
#
# Usage:
#   scripts/fix-rotated-key-refs.sh --dry-run [--sweep-file P] [--env-file P]
#   scripts/fix-rotated-key-refs.sh           [--sweep-file P] [--env-file P]
#
# Must run on the Unraid host. Requires: docker, grep, sed, awk.

set -euo pipefail

DRY_RUN=false
SWEEP_FILE="/root/keysweep.$(date -u +%Y%m%d).txt"
ENV_FILE="/root/homepage-secrets.$(date -u +%Y%m%d).env"
LOG_FILE=""
STAMP="$(date -u +%Y%m%dT%H%MZ)"

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)    DRY_RUN=true; shift ;;
        --sweep-file) SWEEP_FILE="$2"; shift 2 ;;
        --env-file)   ENV_FILE="$2"; shift 2 ;;
        --log-file)   LOG_FILE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done
log(){ local l="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; echo "$l"; [ -n "$LOG_FILE" ] && echo "$l" >> "$LOG_FILE"; return 0; }

[ -f "$SWEEP_FILE" ] || { echo "sweep file not found: $SWEEP_FILE" >&2; exit 1; }
[ -f "$ENV_FILE" ]   || { echo "env file not found: $ENV_FILE" >&2; exit 1; }

nb(){ ls -t "$1".bak.* 2>/dev/null | head -1; }
nk(){ grep "^HOMEPAGE_VAR_${1}_KEY=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

declare -A OLD NEW
OLD[sonarr]=$(grep -oE '<ApiKey>[^<]+'  "$(nb /mnt/cache/appdata/binhex-sonarr/config.xml)"  | sed 's/<ApiKey>//')
OLD[radarr]=$(grep -oE '<ApiKey>[^<]+'  "$(nb /mnt/cache/appdata/binhex-radarr/config.xml)"  | sed 's/<ApiKey>//')
OLD[prowlarr]=$(grep -oE '<ApiKey>[^<]+' "$(nb /mnt/cache/appdata/prowlarr/config.xml)"      | sed 's/<ApiKey>//')
OLD[bazarr]=$(awk '/^auth:/{a=1} a&&/^[[:space:]]+apikey:/{print $2; exit}' "$(nb /mnt/cache/appdata/bazarr/config/config.yaml)")
OLD[sabnzbd]=$(awk -F'= ' '/^api_key = /{print $2; exit}'  "$(nb /mnt/cache/appdata/binhex-sabnzbdvpn/sabnzbd.ini)")
OLD[tautulli]=$(awk -F'= ' '/^api_key = /{print $2; exit}'  "$(nb /mnt/cache/appdata/tautulli/config.ini)")
OLD[gluetun]=$(grep -oE 'apikey = "[^"]+'  "$(nb /mnt/cache/appdata/gluetun/auth/config.toml)" | sed 's/apikey = "//')
for s in sonarr radarr prowlarr bazarr sabnzbd tautulli gluetun; do
    NEW[$s]=$(nk "$(echo "$s" | tr a-z A-Z)")
    o="${OLD[$s]:-}"; n="${NEW[$s]:-}"
    [ -n "$o" ] && [ -n "$n" ] || { log "ERROR $s: missing old/new key"; exit 1; }
    [ "$o" != "$n" ] || { log "ERROR $s: old == new"; exit 1; }
    [ "${#o}" = "${#n}" ] || { log "ERROR $s: length mismatch ${#o}/${#n}"; exit 1; }
done

# --- build: container -> list of "file:key,key" ---------------------------
# map a file path to the container whose bind-mount contains it
declare -A MOUNT2C
while read -r cname; do
    while read -r src; do
        [ -n "$src" ] && MOUNT2C["$src"]="$cname"
    done < <(docker inspect "$cname" --format '{{range .Mounts}}{{println .Source}}{{end}}' 2>/dev/null)
done < <(docker ps -a --format '{{.Names}}')

owner_of(){
    local path="$1" best="" blen=0 m
    for m in "${!MOUNT2C[@]}"; do
        case "$path" in
            "$m"/*) [ "${#m}" -gt "$blen" ] && { best="${MOUNT2C[$m]}"; blen=${#m}; } ;;
        esac
    done
    echo "$best"
}

declare -A CFILES   # container -> newline list of files
UNOWNED=""
while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*|"==="*) continue ;; esac
    f="${line%% -->*}"
    [ -f "$f" ] || continue
    case "$f" in *.bak|*.bak.*|*.prop-bak.*|*.keyfix-bak.*|*.log|*.log.*) continue ;; esac
    c="$(owner_of "$f")"
    if [ -z "$c" ]; then UNOWNED="${UNOWNED}${f}"$'\n'; continue; fi
    CFILES[$c]="${CFILES[$c]:-}${f}"$'\n'
done < "$SWEEP_FILE"

[ -n "$UNOWNED" ] && log "WARN: no owning container for:"$'\n'"$UNOWNED"

log "=== fix-rotated-key-refs (dry_run=${DRY_RUN}) — ${#CFILES[@]} container(s) ==="
changed=(); failed=()

for c in "${!CFILES[@]}"; do
    log "--- $c ---"
    mapfile -t files < <(printf '%s' "${CFILES[$c]}" | sed '/^$/d' | sort -u)
    # which keys appear across this container's files
    declare -A hitkeys=()
    for f in "${files[@]}"; do
        for s in sonarr radarr prowlarr bazarr sabnzbd tautulli gluetun; do
            n=$(grep -c -F "${OLD[$s]}" "$f" 2>/dev/null || true)
            [ "$n" -gt 0 ] && { log "  $f : OLD $s x$n"; hitkeys[$s]=1; }
        done
    done
    if [ "${#hitkeys[@]}" -eq 0 ]; then log "  (nothing live) "; unset hitkeys; continue; fi
    if $DRY_RUN; then log "  would stop $c, swap [${!hitkeys[*]}], restart"; unset hitkeys; continue; fi

    running=$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo false)
    [ "$running" = "true" ] && docker stop "$c" >/dev/null && log "  stopped $c"
    for f in "${files[@]}"; do
        cp "$f" "${f}.keyfix-bak.${STAMP}"
        for s in "${!hitkeys[@]}"; do sed -i "s|${OLD[$s]}|${NEW[$s]}|g" "$f"; done
    done
    stale=0
    for f in "${files[@]}"; do for s in "${!hitkeys[@]}"; do
        n=$(grep -c -F "${OLD[$s]}" "$f" 2>/dev/null || true); stale=$((stale+n))
    done; done
    if [ "$stale" -ne 0 ]; then
        log "  ERROR: $stale stale left — restoring ${#files[@]} file(s)"
        for f in "${files[@]}"; do cp "${f}.keyfix-bak.${STAMP}" "$f"; done
        [ "$running" = "true" ] && docker start "$c" >/dev/null
        failed+=("$c"); unset hitkeys; continue
    fi
    [ "$running" = "true" ] && docker start "$c" >/dev/null && log "  restarted $c"
    changed+=("$c"); unset hitkeys
done

log "=== done: fixed=[${changed[*]:-}] failed=[${failed[*]:-}] ==="
[ ${#failed[@]} -eq 0 ]
