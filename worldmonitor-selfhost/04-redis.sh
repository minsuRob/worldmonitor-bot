#!/usr/bin/env bash
# Redis 7 bound to 127.0.0.1 with password from .env (host network).
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
set -a; . "$WM_DIR/.env"; set +a
mkdir -p "$TOOLS_DIR/redis-data"
sudo env PATH="$PATH" docker rm -f worldmonitor-redis >/dev/null 2>&1 || true
sudo env PATH="$PATH" docker run -d --name worldmonitor-redis --network host --restart unless-stopped \
  -v "$TOOLS_DIR/redis-data:/data" redis:7-alpine \
  redis-server --bind 127.0.0.1 --port 6379 --requirepass "$REDIS_PASSWORD" --appendonly yes --maxmemory 1gb >/dev/null
echo "redis started on 127.0.0.1:6379"
