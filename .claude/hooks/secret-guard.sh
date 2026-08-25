#!/usr/bin/env bash
# PreToolUse guard against accidental plaintext secret exposure in this
# homelab-infra container's transcript. Blocks before execution rather than
# trying to redact after the fact (PostToolUse can't rewrite tool output).
#
# Thin wrapper: all decision logic lives in secret_guard_check.py, which
# does heredoc-aware statement splitting and per-statement analysis. An
# earlier pure-bash/regex version kept breaking on multi-line commands --
# grep/sed's `$` anchors to the end of every line (not the whole string) on
# multi-line input, so a naive "does this end in a redirect" check got
# fooled by an unrelated earlier line's `>`, and a follow-up newline-split
# fix then broke heredocs (`cat > file <<'EOF' ... EOF`). See the .py file's
# docstring and /root/.claude/projects/-workspace/memory/
# project_secret_guard_hook.md for the incident history.
set -euo pipefail

input="$(cat)"

parsed="$(python3 -c '
import json, sys, base64
d = json.load(sys.stdin)
tn = d.get("tool_name", "") or ""
ti = d.get("tool_input", {}) or {}
cmd = ti.get("command", "") or ""
fp = ti.get("file_path", "") or ""
print(tn)
print(base64.b64encode(cmd.encode()).decode())
print(base64.b64encode(fp.encode()).decode())
' <<<"$input")"

tool_name="$(sed -n '1p' <<<"$parsed")"
command_b64="$(sed -n '2p' <<<"$parsed")"
file_path_b64="$(sed -n '3p' <<<"$parsed")"
command="$(base64 -d <<<"$command_b64" 2>/dev/null || true)"
file_path="$(base64 -d <<<"$file_path_b64" 2>/dev/null || true)"

deny() {
  local reason="$1"
  python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": sys.argv[1]}}))
' "$reason"
  exit 0
}

CHECK="/workspace/.claude/hooks/secret_guard_check.py"

if [[ "$tool_name" == "Bash" ]]; then
  verdict="$(printf '%s' "$command" | python3 "$CHECK")"
  if [[ "$verdict" == DENY:* ]]; then
    deny "${verdict#DENY:}"
  fi
fi

if [[ "$tool_name" == "Read" ]]; then
  verdict="$(python3 "$CHECK" --read "$file_path")"
  if [[ "$verdict" == DENY:* ]]; then
    deny "${verdict#DENY:}"
  fi
fi

exit 0
