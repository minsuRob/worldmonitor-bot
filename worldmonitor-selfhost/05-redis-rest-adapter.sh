#!/usr/bin/env bash
# Upstash-compatible REST adapter on $REST_PORT. Uses the upstream file docker/redis-rest-proxy.mjs
# from the clone (mirrors Dockerfile.redis-rest) with a local redis@4 install. Bearer token = REDIS_TOKEN.
# NOTE: upstream proxy listens on 0.0.0.0 (no host option); keep the port firewalled / box-local.
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
set -a; . "$WM_DIR/.env"; set +a
D="$TOOLS_DIR/redis-rest"; mkdir -p "$D"
cp "$WM_DIR/docker/redis-rest-proxy.mjs" "$D/"
[ -d "$D/node_modules/redis" ] || (cd "$D" && npm init -y >/dev/null && npm install redis@4 >/dev/null)
cd "$D"
REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379" SRH_TOKEN="$REDIS_TOKEN" PORT="$REST_PORT" \
  setsid nohup node redis-rest-proxy.mjs > "$TOOLS_DIR/redis-rest.log" 2>&1 < /dev/null &
sleep 2; tail -2 "$TOOLS_DIR/redis-rest.log"
