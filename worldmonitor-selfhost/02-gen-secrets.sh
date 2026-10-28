#!/usr/bin/env bash
# Generate local-only secrets into $WM_DIR/.env and .env.local (mode 600). Never prints values.
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
umask 077; cd "$WM_DIR"
if [ ! -f .env ]; then
  { echo "RELAY_SHARED_SECRET=$(openssl rand -hex 32)"
    echo "REDIS_PASSWORD=$(openssl rand -hex 32)"
    echo "REDIS_TOKEN=$(openssl rand -hex 32)"
    echo "WM_SESSION_SECRET=$(openssl rand -hex 32)"; } > .env
fi
TOKEN_LINE=$(grep '^REDIS_TOKEN=' .env); TOKEN=${TOKEN_LINE#REDIS_TOKEN=}
{ echo "UPSTASH_REDIS_REST_URL=http://127.0.0.1:${REST_PORT}"
  echo "UPSTASH_REDIS_REST_TOKEN=${TOKEN}"; } > .env.local
echo "wrote .env and .env.local (values not shown)"
