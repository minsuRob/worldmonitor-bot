#!/usr/bin/env bash
# World Monitor dev server (vite) on localhost:$WM_PORT; reads .env/.env.local.
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
cd "$WM_DIR"
DEV_PORT="$WM_PORT" setsid nohup npm run dev > "$TOOLS_DIR/wm-dev.log" 2>&1 < /dev/null &
sleep 8; curl -s -o /dev/null -w "dev server http %{http_code}\n" "http://localhost:$WM_PORT/"
