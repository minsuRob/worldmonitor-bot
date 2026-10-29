#!/usr/bin/env bash
# PAPER ONLY. Stock desk entry point (box). Same shape as desk/manual/variants.sh.
#   manual/variants.sh prepare <slot>              # screens -> jobs.jsonl (LLM books) + PENDING orders (numeric books)
#   manual/variants.sh finish <runId> [--no-judge] # Mac results -> decide -> PENDING orders
#   manual/variants.sh slot <name>                 # fill slot: marks -> RISK -> fills -> exits -> equity
#   manual/variants.sh due [--run]                 # box cron (*/5): code-only slots whose window is open
#   manual/variants.sh report [--json] [--series daily|weekly] [--since YYYY-MM-DD] [--csv path]
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  prepare|finish|slot|due) exec python3 run.py "$@" ;;
  report) shift; exec python3 report.py "$@" ;;
  *) sed -n 2,8p "$0"; exit 2 ;;
esac
