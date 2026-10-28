#!/usr/bin/env bash
# The 3 READY checks (self-hosted only; never api.worldmonitor.app) + DexScreener + Kalshi + Polymarket. Read-only.
. "$(dirname "$0")/00-env.sh"
for u in "http://localhost:$WM_PORT/api/market/v1/get-fear-greed-index" \
         "http://localhost:$WM_PORT/api/prediction/v1/list-prediction-markets?page_size=1" \
         "http://localhost:$WM_PORT/api/intelligence/v1/list-cross-source-signals" \
         "https://api.dexscreener.com/latest/dex/search?q=BONK" \
         "https://external-api.kalshi.com/trade-api/v2/markets?limit=100&status=open" \
         "https://gamma-api.polymarket.com/markets?closed=false&order=volumeNum&limit=50"; do
  out=$(curl -s -m 20 -w '\n%{http_code} %{time_total}s' "$u"); meta=${out##*$'\n'}; body=${out%$'\n'*}
  echo "$meta  $u"; echo "   ${body:0:140}"
done
