#!/bin/bash
# claude-hub.sh — container-based tmux hub for all Claude Code projects

set -euo pipefail

SESSION="claude-hub"
INIT_ONLY=false
[ "${1:-}" = "--init" ] && INIT_ONLY=true

if tmux has-session -t "$SESSION" 2>/dev/null; then
    $INIT_ONLY && exit 0   # boot-time call: session already exists, nothing to do
    tmux attach -t "$SESSION"
    exit 0
fi

# Local container shell
tmux new-session -d -s "$SESSION" -n local \
    "cd /workspace && exec $SHELL"

# Unraid host — TERM override avoids "missing or unsuitable terminal: tmux-256color"
# since Unraid's terminfo db lacks the nested-tmux entry
tmux new-window -t "$SESSION" -n unraid \
    "TERM=xterm-256color ssh unraid -t 'tmux new -A -s unraid'"
tmux set-window-option -t "$SESSION:unraid" remain-on-exit on

# HA VM
tmux new-window -t "$SESSION" -n ha \
    "TERM=xterm-256color ssh ha -t 'tmux new -A -s ha'"
tmux set-window-option -t "$SESSION:ha" remain-on-exit on

tmux select-window -t "$SESSION:0"

$INIT_ONLY && exit 0   # boot-time call: session created detached, nothing to attach to yet
tmux attach -t "$SESSION"
