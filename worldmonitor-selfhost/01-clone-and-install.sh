#!/usr/bin/env bash
# Clone koala73/worldmonitor (AGPL, third-party — not vendored in this repo) and install deps locally.
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
node -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)' || { echo "need node >= 20"; exit 1; }
[ -d "$WM_DIR/.git" ] || git clone --depth 1 https://github.com/koala73/worldmonitor.git "$WM_DIR"
cd "$WM_DIR" && npm install          # local install only, no -g
