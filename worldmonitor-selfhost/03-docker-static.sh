#!/usr/bin/env bash
# Only needed when apt/docker packages are unavailable (as on the box). Uses Docker's static binaries.
# Starts dockerd WITHOUT iptables/bridge (sandbox limitation) -> containers must use --network host.
set -euo pipefail; . "$(dirname "$0")/00-env.sh"
mkdir -p "$TOOLS_DIR" "$TOOLS_DIR/docker-data"
if [ ! -x "$TOOLS_DIR/docker/dockerd" ]; then
  curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz | tar -xz -C "$TOOLS_DIR"
fi
pgrep -x dockerd >/dev/null || sudo env PATH="$PATH" setsid nohup "$TOOLS_DIR/docker/dockerd" \
  --data-root "$TOOLS_DIR/docker-data" --iptables=false --ip6tables=false --bridge=none \
  > "$TOOLS_DIR/dockerd.log" 2>&1 < /dev/null &
sleep 5; sudo env PATH="$PATH" docker version --format '{{.Server.Version}}'
