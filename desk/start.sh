#!/usr/bin/env bash
# Start CHIEF (which starts the 6 bots) in the background. Paper only.
cd "$(dirname "$0")"
if [ -f state/chief.pid ] && kill -0 "$(cat state/chief.pid)" 2>/dev/null; then echo "already running pid $(cat state/chief.pid)"; exit 0; fi
export WM_PORT="${WM_PORT:-3000}"
setsid nohup python3 chief.py >> logs/chief.out 2>&1 < /dev/null &
sleep 2; echo "CHIEF pid $(cat state/chief.pid)"
