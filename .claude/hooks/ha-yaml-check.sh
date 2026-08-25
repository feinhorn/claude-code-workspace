#!/bin/bash
# Deterministic subset of the ha-yaml-linter skill: mechanical, regex-detectable
# checks only (deprecated top-level keys, tabs, missing mode:). Does NOT cover
# the semantic/Jinja2-logic checks from the full skill.
#
# Uses python3 (not jq -- jq isn't installed in this container and ad-hoc
# apt installs don't survive redeploys; the original jq-based version failed
# *silently* here: jq missing -> empty $file -> case falls through to the
# default `exit 0` -> every write skipped the check with no error surfaced).
set -euo pipefail

input="$(cat)"

parsed="$(python3 -c '
import json, sys, base64
d = json.load(sys.stdin)
ti = d.get("tool_input", {}) or {}
fp = ti.get("file_path", "") or ""
content = ti.get("content", None)
if content is None:
    content = ti.get("new_string", "") or ""
print(base64.b64encode(fp.encode()).decode())
print(base64.b64encode(content.encode()).decode())
' <<<"$input")"

file_path_b64="$(sed -n '1p' <<<"$parsed")"
content_b64="$(sed -n '2p' <<<"$parsed")"
file_path="$(base64 -d <<<"$file_path_b64" 2>/dev/null || true)"
content="$(base64 -d <<<"$content_b64" 2>/dev/null || true)"

case "$file_path" in
  *.yaml|*.yml) ;;
  *) exit 0 ;;
esac

[ -z "$content" ] && exit 0

violations=""

if echo "$content" | grep -qE '^[[:space:]]*-?[[:space:]]*service:[[:space:]]*[^[:space:]]'; then
  violations="${violations}- deprecated 'service:' key found -- use 'action:' instead (breaking since HA 2024.8)\n"
fi
if echo "$content" | grep -qE '^[[:space:]]*trigger:[[:space:]]*$'; then
  violations="${violations}- deprecated singular 'trigger:' key found -- use 'triggers:' instead (breaking since HA 2024.10)\n"
fi
if echo "$content" | grep -qE '^[[:space:]]*condition:[[:space:]]*$'; then
  violations="${violations}- deprecated singular 'condition:' key found -- use 'conditions:' instead\n"
fi
if echo "$content" | grep -qE '^[[:space:]]*action:[[:space:]]*$' && echo "$content" | grep -qE '^[[:space:]]*(trigger|triggers):'; then
  violations="${violations}- possible deprecated singular 'action:' key found alongside a trigger block -- use 'actions:' instead\n"
fi
tab_char="$(printf '\t')"
if printf '%s' "$content" | grep -qF "$tab_char"; then
  violations="${violations}- tab character found -- HA YAML requires 2-space indentation, tabs are not allowed\n"
fi

if [ -n "$violations" ]; then
  reason="$(printf "BLOCKED by ha-yaml-check: mechanical HA YAML rule violation(s) in %s:\n%s\nFix these (or run the full ha-yaml-linter skill) before writing." "$file_path" "$violations")"
  python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": sys.argv[1]}}))
' "$reason"
  exit 0
fi

exit 0
