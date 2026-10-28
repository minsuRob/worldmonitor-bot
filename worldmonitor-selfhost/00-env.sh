#!/usr/bin/env bash
# Shared paths. Edit if your layout differs.
export WM_DIR="${WM_DIR:-$HOME/worldmonitor}"          # git clone of koala73/worldmonitor
export TOOLS_DIR="${TOOLS_DIR:-$HOME/wm-tools}"        # docker binaries, redis data, REST adapter
export WM_PORT="${WM_PORT:-3000}"                      # vite dev port (use next free port if 3000 is taken)
export REST_PORT="${REST_PORT:-8079}"                  # Upstash-compatible REST adapter port
export PATH="$TOOLS_DIR/docker:$PATH"
