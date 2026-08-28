#!/bin/bash
# Unit tests for rotate-homepage-keys.sh's edit_key() — verifies each service's
# in-place key rewrite hits the right field, uses a valid key, and leaves the
# rest of the config byte-for-byte intact. No containers, no network.
#
# Run:  bash scripts/test-rotate-homepage-keys.sh
set -u

ROTATE_LIB_ONLY=1 source "$(dirname "$0")/rotate-homepage-keys.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

NEW="$(gen_key)"
# gen_key format
[[ "$NEW" =~ ^[0-9a-f]{32}$ ]] && ok "gen_key -> 32 lowercase hex" || bad "gen_key format: $NEW"

# ---- fixtures ----
cat > "$TMP/sonarr.xml" <<'EOF'
<Config>
  <BindAddress>*</BindAddress>
  <Port>8989</Port>
  <ApiKey>27eded90434e4a44967ba82dd3c3557e</ApiKey>
  <AuthenticationMethod>Forms</AuthenticationMethod>
  <UrlBase></UrlBase>
</Config>
EOF

cat > "$TMP/sabnzbd.ini" <<'EOF'
[misc]
username = admin
password = hunter2
api_key = 773bb1f5501e4f7eb3ab09f53ed6e82d
nzb_key = 111bb1f5501e4f7eb3ab09f53ed6e999
[servers]
EOF

cat > "$TMP/tautulli.ini" <<'EOF'
[General]
api_enabled = 1
api_key = 4qRU4DeLiQd1FBDVoiuqjxuN2pZOk7Qx
[Cloudinary]
cloudinary_api_key = SHOULDNOTCHANGE0000000000000000000
EOF

cat > "$TMP/bazarr.yaml" <<'EOF'
addic7ed:
  username: ''
auth:
  apikey: 7f012991299046600d84fbcce94f2129
  type: null
radarr:
  apikey: aaaa2991299046600d84fbcce94f0000
  ip: 192.168.1.38
sonarr:
  apikey: bbbb2991299046600d84fbcce94f1111
EOF

cat > "$TMP/gluetun.toml" <<'EOF'
[[roles]]
name = "homepage"
auth = "apikey"
apikey = "shortkey123"
routes = ["GET /v1/publicip/ip"]
EOF

check_unchanged_except() {
    # $1 fixture  $2 backup  $3 grep-pattern of the one line allowed to differ
    local diff_lines
    diff_lines=$(diff "$2" "$1" | grep -cE '^[<>]' || true)
    if [ "$diff_lines" -eq 2 ] && ! diff "$2" "$1" | grep -E '^[<>]' | grep -qvE "$3"; then
        return 0
    fi
    diff "$2" "$1" || true
    return 1
}

test_one() {
    local name="$1" file="$2" newkey="$3" allowed_re="$4" mustcontain="$5"
    cp "$file" "$file.bak"
    edit_key "$name" "$file" "$newkey"
    if ! grep -qF "$mustcontain" "$file"; then
        bad "$name: new key not present as expected ($mustcontain)"; return
    fi
    if grep -qE '(27eded90434e4a44967ba82dd3c3557e|773bb1f5501e4f7eb3ab09f53ed6e82d|4qRU4DeLiQd1FBDVoiuqjxuN2pZOk7Qx|7f012991299046600d84fbcce94f2129|shortkey123)' "$file"; then
        bad "$name: old key still in file"; return
    fi
    if check_unchanged_except "$file" "$file.bak" "$allowed_re"; then
        ok "$name: only the target line changed"
    else
        bad "$name: unexpected collateral change"
    fi
}

test_one sonarr   "$TMP/sonarr.xml"   "$NEW" 'ApiKey'   "<ApiKey>$NEW</ApiKey>"
test_one sabnzbd  "$TMP/sabnzbd.ini"  "$NEW" 'api_key'  "api_key = $NEW"
test_one tautulli "$TMP/tautulli.ini" "$NEW" 'api_key ' "api_key = $NEW"
test_one bazarr   "$TMP/bazarr.yaml"  "$NEW" 'apikey'   "apikey: $NEW"
test_one gluetun  "$TMP/gluetun.toml" "$NEW" 'apikey'   "apikey = \"$NEW\""

# targeted anti-regression checks
grep -q 'nzb_key = 111bb1f5501e4f7eb3ab09f53ed6e999' "$TMP/sabnzbd.ini" \
    && ok "sabnzbd: nzb_key untouched" || bad "sabnzbd: nzb_key changed"
grep -q 'cloudinary_api_key = SHOULDNOTCHANGE0000000000000000000' "$TMP/tautulli.ini" \
    && ok "tautulli: cloudinary_api_key untouched" || bad "tautulli: cloudinary_api_key changed"
grep -q 'apikey: aaaa2991299046600d84fbcce94f0000' "$TMP/bazarr.yaml" \
    && ok "bazarr: radarr apikey untouched" || bad "bazarr: radarr apikey changed"
grep -q 'apikey: bbbb2991299046600d84fbcce94f1111' "$TMP/bazarr.yaml" \
    && ok "bazarr: sonarr apikey untouched" || bad "bazarr: sonarr apikey changed"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
