#!/usr/bin/env bash
# Stop dev server, REST adapter, seeders, redis container (data kept). Does not touch the desk.
. "$(dirname "$0")/00-env.sh"
pkill -f "$WM_DIR/node_modules/.bin/vite" ; pkill -f "redis-rest-proxy.mjs" ; pkill -f "scripts/run-seeders.sh"
sudo env PATH="$PATH" docker stop worldmonitor-redis >/dev/null 2>&1; echo stopped
