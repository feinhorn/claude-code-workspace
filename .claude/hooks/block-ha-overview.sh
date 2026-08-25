#!/usr/bin/env bash
# PreToolUse hook -- matcher: mcp__homeassistant__ha_get_overview and the
# ha_call_read_tool/ha_call_write_tool/ha_call_delete_tool proxy tools.
#
# Real incident (2026-08-21): ha_get_overview's response always embeds the
# live HA MCP connection token in `settings_url_hint`/`settings_url`, no
# matter what `fields=` projection is passed -- confirmed via the tool's own
# schema description ("emitted regardless of fields= projection"). A
# PreToolUse hook can only gate a Bash/Read *input* before it runs; there is
# no hook mechanism that can rewrite an MCP tool's *response* after it comes
# back, so the only real fix is to never let this specific call happen.
#
# Extended same day: the ha-mcp add-on's tool surface also exposes a proxy
# pattern (ha_call_read_tool(name=..., arguments=...)) that can invoke
# ha_get_overview under a DIFFERENT tool name entirely -- a direct-name-only
# matcher misses this completely, since the hook only ever sees
# "mcp__homeassistant__ha_call_read_tool" as tool_name, not
# "...ha_get_overview". Found via deliberately testing the bypass right
# after deploying the direct-name block; caught only by Claude Code's
# generic auto-mode classifier that time, not by this hook, which is a
# probabilistic safety net, not a guarantee. Closed here by also inspecting
# tool_input.name for the three proxy tools.
set -euo pipefail

input="$(cat)"

verdict="$(python3 -c '
import json, sys
d = json.load(sys.stdin)
tool_name = d.get("tool_name", "") or ""
tool_input = d.get("tool_input", {}) or {}

blocked = False
if tool_name == "mcp__homeassistant__ha_get_overview":
    blocked = True
elif tool_name in (
    "mcp__homeassistant__ha_call_read_tool",
    "mcp__homeassistant__ha_call_write_tool",
    "mcp__homeassistant__ha_call_delete_tool",
):
    if tool_input.get("name", "") == "ha_get_overview":
        blocked = True

print("BLOCK" if blocked else "ALLOW")
' <<<"$input")"

if [[ "$verdict" == "BLOCK" ]]; then
  python3 -c '
import json
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "Blocked: ha_get_overview (direct or via the ha_call_*_tool proxy) "
            "always embeds the live HA MCP connection token in "
            "settings_url_hint/settings_url, regardless of any fields= "
            "projection -- confirmed a real incident 2026-08-21. No hook can "
            "redact this after the fact (PreToolUse only gates inputs, not MCP "
            "responses). Use a narrower tool instead: ha_get_state, ha_search, "
            "ha_list_floors_areas, ha_get_entity, etc. If you specifically need "
            "system-wide domain/entity counts, ask the user to check the HA UI "
            "directly rather than calling this tool."
        ),
    }
}))
'
fi

exit 0
