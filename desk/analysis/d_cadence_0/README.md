# Book D exit-cadence replay: token "0" (+ Lowo)
Read-only analysis run 2026-10-29 ~13:15 KST. Nothing in the desk's code, config, ledgers or routines was changed.
- Data: GeckoTerminal public API, 1-minute OHLCV (USD, base token).
  - "0": pool H5EcTJgm…GbW (0/ZEC, created 10:10 KST). File: ohlcv_1m.json, 10:10–13:10 KST.
  - Lowo: pool BQf17Xv8…r6s. File: lowo_ohlcv_1m.json, 11:53–13:11 KST.
  - Snapshots: pool_0.json and dexscreener_pair_0.json.
- Entry, qty and exits come from state/variants/D.db. The fill model copies common.py amm_sell/fee_for.
- A check at time t sees the close of the last finished 1-minute candle (gaps forward-filled).
- simulate.py → simulate.out (token "0"). lowo_and_speed.py → lowo_and_speed.out.
- Not modeled: the shared RISK volume rule. It never fired in the real run (ratio 4.0).
