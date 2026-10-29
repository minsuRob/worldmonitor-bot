"""Live, READ-ONLY Toss check (not a unit test). Needs stockdesk/.env (TOSS_CLIENT_ID / TOSS_CLIENT_SECRET) and this machine's
public IP in Toss settings → Open API → allowed IP. Uses the shared token cache in state/market.db (one valid token per
client: issuing a new one revokes the old, so this script never forces a new token). Never prints keys or the token.

  python3 manual/toss_smoke.py [KRX_CODE] [US_CODE]      (default 005930 AAPL)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as C
import quotes as Q

def main():
    krx = sys.argv[1] if len(sys.argv) > 1 else "005930"; us = sys.argv[2] if len(sys.argv) > 2 else "AAPL"
    tq = Q.get_source("toss")
    if tq is None: sys.exit("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET not set (stockdesk/.env)")
    try:
        tq._token(); print("token: OK (cached in state/market.db kv; value not shown)")
    except RuntimeError as e:
        sys.exit(f"token: FAILED {e} — check client id/secret and the allowed IP")
    checks = [
        ("quote KRX", lambda: tq.quote("KRX", krx)),
        ("quote US", lambda: tq.quote("US", us)),
        ("daily_bars KRX x5", lambda: tq.daily_bars("KRX", krx, 5)),
        ("ranking KRX turnover x5", lambda: tq.ranking("KRX", "turnover", 5)),
        ("stock_flags KRX", lambda: tq.stock_flags("KRX", krx)),
        ("investor_flow KRX x3", lambda: tq.investor_flow(krx, 3)),
        ("fx USD/KRW mid", lambda: tq.fx_rate()),
    ]
    bad = 0
    for label, fn in checks:
        out, err = fn()
        ok = err is None and out not in (None, [], {})
        bad += 0 if ok else 1
        if isinstance(out, list): shown = out[-3:]
        elif isinstance(out, dict): shown = {k: v for k, v in out.items() if k != "ts"}
        else: shown = out
        print(f"- {label}: {'OK' if ok else 'FAIL ' + str(err)} {str(shown)[:300]}")
    print(f"total Toss calls: {tq.calls}; failures: {bad}")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
