#!/bin/bash
# rotate-homepage-keys.sh — rotate the Homepage-dashboard widget API keys that
# were exposed in a Claude Code transcript on 2026-08-28 (services.yaml `key:`
# fields printed in plaintext by `secret_guard_check.py --redact`, whose
# SECRET_KEY_NAME_RE didn't match a bare `key` at the time).
#
# Covers the 7 "Phase A" credentials — the ones with a machine-generatable key
# that lives in a text config file on the Unraid host:
#
#     sonarr  radarr  prowlarr  bazarr  sabnzbd  tautulli  gluetun
#
# For each: generate a fresh key, back up the config, stop the container, edit
# the key in place, restart, and verify the new key works against the service's
# own API. On any verification failure the config backup is restored and the
# container restarted before the script aborts.
#
# The new key values are written ONLY to an 0600 env file (default
# /root/homepage-secrets.<date>.env) — never printed, never logged. That file is
# what Homepage's compose stack should reference via {{HOMEPAGE_VAR_*}}
# placeholders (Phase B — see the Notion "Credential Rotation Needed" page).
#
# NOT handled here (Phase C — no key-mint API / account-scoped, do manually):
#     Unraid API key   UniFi API key   Plex token
# NOT handled here (downstream propagation): updating each consumer's stored
# copy of a rotated key. The script prints an exact checklist at the end.
#
# Usage:
#   scripts/rotate-homepage-keys.sh --dry-run                 # preflight only, touches nothing
#   scripts/rotate-homepage-keys.sh                           # rotate all 7
#   scripts/rotate-homepage-keys.sh --only tautulli           # rotate just one
#   scripts/rotate-homepage-keys.sh --restore 20260828T1200Z  # roll back a prior run's backups
#
# Options:
#   --dry-run            Report what would happen; generate no keys, change nothing.
#   --only SERVICE       Act on a single service (repeatable).
#   --restore STAMP      Restore every *.bak.<STAMP> this script wrote, restart those containers, exit.
#   --out-env PATH       Where to append new HOMEPAGE_VAR_* lines (default /root/homepage-secrets.<date>.env).
#   --log-file PATH      Also append timestamped log lines here.
#
# Must run on the Unraid host (needs docker + the /mnt/cache/appdata paths).
# Requires: docker, openssl, curl, awk, sed, grep, sha256sum — all present on Unraid 7.
#
# Secrets are never accepted as flags and never emitted to stdout/stderr/logs.

set -euo pipefail

DRY_RUN=false
RESTORE_STAMP=""
declare -a ONLY=()
LOG_FILE=""
OUT_ENV="/root/homepage-secrets.$(date -u +%Y%m%d).env"
TS="$(date -u +%Y%m%dT%H%MZ)"

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)   DRY_RUN=true; shift ;;
        --only)      ONLY+=("$2"); shift 2 ;;
        --restore)   RESTORE_STAMP="$2"; shift 2 ;;
        --out-env)   OUT_ENV="$2"; shift 2 ;;
        --log-file)  LOG_FILE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

log() {
    local line
    line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
    echo "$line"
    [ -n "$LOG_FILE" ] && echo "$line" >> "$LOG_FILE"
    return 0
}

# name|container|config_path
SERVICES=(
    "sonarr|binhex-sonarr|/mnt/cache/appdata/binhex-sonarr/config.xml"
    "radarr|binhex-radarr|/mnt/cache/appdata/binhex-radarr/config.xml"
    "prowlarr|prowlarr|/mnt/cache/appdata/prowlarr/config.xml"
    "bazarr|bazarr|/mnt/cache/appdata/bazarr/config/config.yaml"
    "sabnzbd|binhex-sabnzbdvpn|/mnt/cache/appdata/binhex-sabnzbdvpn/sabnzbd.ini"
    "tautulli|tautulli|/mnt/cache/appdata/tautulli/config.ini"
    "gluetun|binhex-official-gluetun|/mnt/cache/appdata/gluetun/auth/config.toml"
)

# All 7 services either use a 32-char lowercase-hex API key natively
# (sonarr/radarr/prowlarr/sabnzbd/bazarr) or accept an arbitrary string with no
# format check (tautulli — native shape is base62/32; gluetun — native 22 chars).
# `openssl rand -hex 16` (= 32 hex chars) is therefore valid for every one.
gen_key() { openssl rand -hex 16; }

selected() {
    [ ${#ONLY[@]} -eq 0 ] && return 0
    local s
    for s in "${ONLY[@]}"; do [ "$s" = "$1" ] && return 0; done
    return 1
}

# --- per-service config edit -------------------------------------------------
# Each writes the new key into $path (already backed up by the caller) and must
# leave the rest of the file byte-for-byte unchanged. Never echoes the key.
edit_key() {
    local name="$1" path="$2" newkey="$3"
    case "$name" in
        sonarr|radarr|prowlarr)
            sed -i "s|<ApiKey>[^<]*</ApiKey>|<ApiKey>${newkey}</ApiKey>|" "$path"
            ;;
        sabnzbd|tautulli)
            # both use `api_key = <value>` in an INI; anchor to line-start so
            # tautulli's `cloudinary_api_key` / sab's `nzb_key` are untouched
            sed -i "s|^api_key = .*|api_key = ${newkey}|" "$path"
            ;;
        bazarr)
            # replace `apikey:` only inside the top-level `auth:` block
            awk -v k="$newkey" '
                /^auth:/            { inauth=1 }
                inauth && /^[A-Za-z]/ && !/^auth:/ { inauth=0 }
                inauth && /^[[:space:]]+apikey:[[:space:]]*/ {
                    sub(/apikey:[[:space:]]*.*/, "apikey: " k); inauth=0
                }
                { print }
            ' "$path" > "${path}.tmp" && mv "${path}.tmp" "$path"
            ;;
        gluetun)
            sed -i "s|apikey = \"[^\"]*\"|apikey = \"${newkey}\"|" "$path"
            ;;
        *) log "ERROR: no edit rule for $name"; return 1 ;;
    esac
}

# --- per-service live verification -----------------------------------------
# Returns 0 iff the service accepts $newkey. Uses only HTTP status / a success
# marker; never prints a response body (could echo other secrets).
verify_key() {
    local name="$1" newkey="$2" code body
    case "$name" in
        sonarr)
            code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
                -H "X-Api-Key: ${newkey}" http://192.168.1.41:8989/api/v3/system/status) ;;
        radarr)
            code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
                -H "X-Api-Key: ${newkey}" http://192.168.1.38:7878/api/v3/system/status) ;;
        prowlarr)
            code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
                -H "X-Api-Key: ${newkey}" http://192.168.1.74:9696/api/v1/system/status) ;;
        bazarr)
            code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
                -H "X-API-KEY: ${newkey}" http://192.168.1.48:6767/api/system/status) ;;
        sabnzbd)
            # mode=queue requires a valid api_key (mode=version does not), so
            # this actually proves the new key works, not just that SAB is up
            body=$(curl -sk --max-time 10 "http://192.168.1.39:8080/api?mode=queue&output=json&apikey=${newkey}")
            case "$body" in *'"queue"'*) code=200 ;; *) code=401 ;; esac ;;
        tautulli)
            body=$(curl -sk --max-time 10 "http://192.168.1.34:8181/api/v2?cmd=arnold&apikey=${newkey}")
            case "$body" in *'"result": "success"'*|*'"result":"success"'*) code=200 ;; *) code=401 ;; esac ;;
        gluetun)
            code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
                -H "X-API-Key: ${newkey}" http://192.168.1.74:8000/v1/publicip/ip) ;;
        *) return 1 ;;
    esac
    [ "$code" = "200" ]
}

probe_reachable() {
    # dry-run helper: is the service HTTP port answering at all (any status)?
    local name="$1" url
    case "$name" in
        sonarr)   url="http://192.168.1.41:8989/ping" ;;
        radarr)   url="http://192.168.1.38:7878/ping" ;;
        prowlarr) url="http://192.168.1.74:9696/ping" ;;
        bazarr)   url="http://192.168.1.48:6767/" ;;
        sabnzbd)  url="http://192.168.1.39:8080/" ;;
        tautulli) url="http://192.168.1.34:8181/" ;;
        gluetun)  url="http://192.168.1.74:8000/" ;;
    esac
    curl -sk -o /dev/null -w '%{http_code}' --max-time 8 "$url" 2>/dev/null || echo "000"
}

wait_for_verify() {
    # VERIFY_TRIES x 2s. Default 30 (60s); bump for slow-booting containers
    # like binhex-sabnzbdvpn which brings up a VPN before the web UI.
    local name="$1" newkey="$2" i tries="${VERIFY_TRIES:-30}"
    for i in $(seq 1 "$tries"); do
        verify_key "$name" "$newkey" && return 0
        sleep 2
    done
    return 1
}

# Test hook: `ROTATE_LIB_ONLY=1 source rotate-homepage-keys.sh` loads the
# functions (gen_key, edit_key, verify_key, ...) without running anything.
[ "${ROTATE_LIB_ONLY:-}" = "1" ] && return 0

# --- restore mode ----------------------------------------------------------
if [ -n "$RESTORE_STAMP" ]; then
    log "=== RESTORE mode: rolling back *.bak.${RESTORE_STAMP} ==="
    for row in "${SERVICES[@]}"; do
        IFS='|' read -r name container path <<< "$row"
        selected "$name" || continue
        bak="${path}.bak.${RESTORE_STAMP}"
        if [ -f "$bak" ]; then
            log "$name: restoring $bak -> $path, restarting $container"
            if ! $DRY_RUN; then
                docker stop "$container" >/dev/null
                cp "$bak" "$path"
                docker start "$container" >/dev/null
            fi
        else
            log "$name: no backup $bak — skipped"
        fi
    done
    log "=== restore complete ==="
    exit 0
fi

# --- main ----------------------------------------------------------------
log "=== Homepage key rotation (stamp=${TS}, dry_run=${DRY_RUN}) ==="
$DRY_RUN || { umask 077; touch "$OUT_ENV"; chmod 600 "$OUT_ENV"; log "new keys will be written to ${OUT_ENV} (0600)"; }

rotated=()
failed=()

for row in "${SERVICES[@]}"; do
    IFS='|' read -r name container path <<< "$row"
    selected "$name" || continue
    log "--- $name ($container) ---"

    # preflight
    if ! docker inspect "$container" >/dev/null 2>&1; then
        log "$name: container '$container' not found — SKIP"; failed+=("$name"); continue
    fi
    if [ ! -f "$path" ]; then
        log "$name: config '$path' not found — SKIP"; failed+=("$name"); continue
    fi
    case "$name" in
        sonarr|radarr|prowlarr) grep -q "<ApiKey>" "$path" || { log "$name: no <ApiKey> in config — SKIP"; failed+=("$name"); continue; } ;;
        sabnzbd|tautulli)       grep -q "^api_key = " "$path" || { log "$name: no 'api_key = ' line — SKIP"; failed+=("$name"); continue; } ;;
        bazarr)                 grep -q "apikey:" "$path" || { log "$name: no apikey: in config — SKIP"; failed+=("$name"); continue; } ;;
        gluetun)                grep -q 'apikey = "' "$path" || { log "$name: no 'apikey = ' in toml — SKIP"; failed+=("$name"); continue; } ;;
    esac

    if $DRY_RUN; then
        log "$name: would back up -> ${path}.bak.${TS}"
        log "$name: would stop $container, rewrite key, restart, verify via API"
        log "$name: HTTP port probe = $(probe_reachable "$name")"
        continue
    fi

    newkey="$(gen_key)"
    cp "$path" "${path}.bak.${TS}"
    log "$name: backed up -> ${path}.bak.${TS}"

    docker stop "$container" >/dev/null
    edit_key "$name" "$path" "$newkey"

    if cmp -s "$path" "${path}.bak.${TS}"; then
        log "$name: ERROR edit changed nothing — restoring, aborting"
        cp "${path}.bak.${TS}" "$path"; docker start "$container" >/dev/null
        failed+=("$name"); continue
    fi

    docker start "$container" >/dev/null
    log "$name: restarted, waiting for API to accept the new key..."

    if wait_for_verify "$name" "$newkey"; then
        printf 'HOMEPAGE_VAR_%s_KEY=%s\n' "$(echo "$name" | tr '[:lower:]' '[:upper:]')" "$newkey" >> "$OUT_ENV"
        log "$name: OK — new key verified, written to ${OUT_ENV}"
        rotated+=("$name")
    else
        log "$name: VERIFY FAILED — restoring ${path}.bak.${TS} and restarting"
        docker stop "$container" >/dev/null
        cp "${path}.bak.${TS}" "$path"
        docker start "$container" >/dev/null
        failed+=("$name")
    fi
    newkey=""
done

log "=== done: rotated=[${rotated[*]:-}] failed/skipped=[${failed[*]:-}] ==="

if [ ${#rotated[@]} -gt 0 ] && ! $DRY_RUN; then
cat <<EOF

────────────────────────────────────────────────────────────────────────
MANUAL PROPAGATION CHECKLIST — the script rotated the primary keys only.
Each consumer below still holds an OLD copy and must be updated by hand
(new values are in ${OUT_ENV}):

  Homepage        Phase B: replace the literal key:/password: values in
                  services.yaml with {{HOMEPAGE_VAR_*}} placeholders and add
                  ${OUT_ENV} as an env_file on the homepage compose service,
                  then Compose Up. Verify /api/services renders with no 401s.

  Prowlarr        Settings -> Apps -> Sonarr & Radarr entries: paste each
                  app's new API key, then "Test" + "Sync App Indexers".

  Sonarr, Radarr  Settings -> Download Clients -> SABnzbd: paste sabnzbd's
                  new API key, "Test", Save.

  Bazarr          Settings -> Sonarr / Settings -> Radarr: paste the new
                  Sonarr/Radarr keys, Save, Test.

  Overseerr/Seerr Settings -> Services -> Sonarr/Radarr: update API keys.

  Notifiarr       Update Sonarr/Radarr/Prowlarr/Tautulli keys in its config.

  Tautulli        Consumers of Tautulli's key (Homepage, Notifiarr) — update
                  from ${OUT_ENV}.

Phase C (do separately, by hand — no mint API): Unraid API key, UniFi API
key, Plex token. See the Notion "Credential Rotation Needed" page.
────────────────────────────────────────────────────────────────────────
EOF
fi

[ ${#failed[@]} -eq 0 ]
