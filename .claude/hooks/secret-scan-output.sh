#!/usr/bin/env bash
# PostToolUse second-line detector: scans every tool result for known secret
# prefixes and high-entropy strings, and raises an immediate warning if one
# appears. This is NOT a substitute for secret-guard.sh's PreToolUse blocking
# -- by the time this runs, the output already reached the transcript, so it
# can only alarm fast, not redact. See secret_scan_output.py's docstring.
set -euo pipefail

python3 /workspace/.claude/hooks/secret_scan_output.py
