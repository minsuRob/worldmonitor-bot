# Paper-only trading desk (NOT started)
Paper trading only. No wallets, keys, exchange logins, or real orders. Public read-only data only.
Start later:  WM_PORT=3000 ./start.sh   (CHIEF launches scan/vet/book/size/fills/risk)
Stop:         ./stop.sh                 (never closes positions)
Report:       python3 report.py [YYYY-MM-DD]   Alert: python3 check_alert.py
State: state/desk.db, state/summary.json   Logs: logs/supervisor.log

## Paper books (manual/variants.sh prepare | finish <runId> [--no-judge] | report)
Five independent $1,000 paper ledgers judged in the same cycle. Rules live in manual/book_rules.py; the shared RISK
rules (unmeasurable close, volume-collapse close, +60% mcap flag) run unchanged in every book and are never loosened;
C and D only ADD their own exits after RISK, using RISK's fresh marks (no extra API calls).

| Book | Ledger | VET (difference from BASE) | Size | Buy rule | Exits |
|---|---|---|---|---|---|
| BASE | state/desk.db | top holder <=5%, liq >=$10k & >=50x order, h1 <25% | Kelly 8.33% capped 6% (~$60) | Claude BUY/SKIP | shared RISK |
| A | variants/A.db | = BASE | = BASE | EV = p_win*payoff - (1-p_win) - 0.03 > 0 | shared RISK |
| B | variants/B.db (old C ledger) | top holder <=8% | = BASE | Claude BUY/SKIP | shared RISK |
| C momentum rider | variants/C.db | top holder <=8%; h1 +10%..<150%, h6 >=0, m5 > -8%, m5 buys >= sells | fixed 10% (~$100), max 5 open | EV > 0 (as A) | RISK + stop -20%, sell 50% at 2x, trail 25% from peak after TP |
| D early sniper | variants/D.db | top holder <=10%; age 5m..24h; liq >=$5k; >=50 holders; m5 buys/sells >=1.3 with >=10 buys; 5m vol pace >=1.2x 1h pace; m5 > -15%; h1 <300% | fixed 5% (~$50; min order $30), max 10 open, 4% slippage budget | numeric signal buys unless Claude vetoes (own rug-veto system prompt; no answer = SKIP) | RISK + stop -35%, sell 50% at 3x, trail 40% from peak after TP |

C pros: trades proven momentum with real flow, tighter stop, locks half at 2x. Cons: buys after the move (late entries,
blow-off tops), 10% tickets make drawdowns fast, few candidates when the market is flat.
D pros: earliest entries, many small tickets, rare 3x+ winners pay for many losers, Claude only blocks obvious rugs.
Cons: young/thin pairs (rugs, low liquidity, bigger slippage), -35% stop means large per-trade losses, low hit rate expected.
2026-10-29 redesign: old B (h1 75%), C (top holder 8%) and D (Kelly cap 12%) ledgers archived to state/variants/archive-20261029/;
old C.db became B.db; new C and D started at $1,000. Tests: python3 manual/tests/test_books_v2.py
