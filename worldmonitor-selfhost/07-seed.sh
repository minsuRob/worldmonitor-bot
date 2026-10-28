#!/usr/bin/env bash
# Seed Redis from public sources. Usage: ./07-seed.sh quick   (keyless seeders that feed the 3 READY checks)
#                                         ./07-seed.sh full    (upstream scripts/run-seeders.sh, ~228 scripts, hours)
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
cd "$WM_DIR"; set -a; . ./.env; . ./.env.local; set +a
if [ "${1:-quick}" = full ]; then
  SEED_TIMEOUT=240 setsid nohup ./scripts/run-seeders.sh > "$TOOLS_DIR/wm-seeders.log" 2>&1 < /dev/null &
  echo "full seeding started in background"; exit 0
fi
for s in fear-greed prediction-markets earthquakes weather-alerts radiation-watch regulatory-actions \
         sanctions-pressure cyber-threats market-quotes commodity-quotes cross-source-signals; do
  f="scripts/seed-$s.mjs"; [ -f "$f" ] || { echo "$s: script not found"; continue; }
  printf '%s: ' "$s"; timeout 240 node "$f" 2>&1 | grep -E "=== Done|FAILURE" | tail -1 || echo "(no summary)"
done
