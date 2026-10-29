#!/usr/bin/env bash
# PAPER ONLY. Variant cycle entry point.
#   manual/variants.sh prepare                 # box: shared SCAN + VET x5 + one deduped jobs.jsonl
#   manual/variants.sh finish <runId> [--no-judge]   # box: import Mac results, SIZE/FILLS/RISK x5
#   manual/variants.sh report [--json]
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  prepare) exec python3 manual/run_variants.py prepare ;;
  finish)  shift; exec python3 manual/run_variants.py finish "$@" ;;
  report)  shift; exec python3 manual/variant_report.py "$@" ;;
  *) sed -n 2,6p "$0"; exit 2 ;;
esac
