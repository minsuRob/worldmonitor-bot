#!/usr/bin/env bash
# Stop CHIEF and its bots. Does NOT close any position.
cd "$(dirname "$0")"
[ -f state/chief.pid ] && kill "$(cat state/chief.pid)" 2>/dev/null && echo "sent TERM to CHIEF $(cat state/chief.pid)"
sleep 3
pkill -f "/workspace/desk/bots.py" 2>/dev/null
echo stopped
