"""Lowo replay (unfilled D signal at 12:05 KST) + speed stats for both D-signal tokens. Same model as simulate.py."""
import json, datetime as dt
from simulate import load, price_at, replay, ideal_stop, fmt, sell, STOP
lo = load('lowo_ohlcv_1m.json')
print("Lowo candles", fmt(min(lo)), "->", fmt(max(lo)), len(lo))
sig_ts = 1793243199.70   # order row ts in D.db (12:06:39 KST), expected_price 7.281e-05
px0 = price_at(lo, sig_ts); print(f"Lowo gecko last-close at signal {px0:.4e} (desk expected 7.281e-05)")
liq = 2 * 30000  # unknown exit liquidity; impact on PnL is ~0.1-0.2% at $49 size
cost = 49.49; qty = (cost - 0.95) / px0
for iv in (1, 2, 5, 10, 15):
    r = replay(lo, sig_ts, px0, qty, cost, liq, iv * 60, max(lo) + 60)
    print(f"{iv:>3} min exit {fmt(r['t'])} seen {r['px']:.4e} ({(r['px']/px0-1)*100:+.1f}%) {r['rule']} PnL ${r['pnl']:+.2f}")
m, f = ideal_stop(lo, sig_ts, px0); print("continuous stop minute", fmt(m) if m else None)
print("Lowo after signal (5-min samples):", [(fmt(t)[:5], f"{(lo[t][4]/px0-1)*100:+.0f}%") for t in sorted(lo) if t >= sig_ts][::5][:14])

def windows(c, start, win=15):
    ts = [t for t in sorted(c) if t >= start]; n = big_dd = big_sw = 0
    for t0 in ts:
        if t0 + win * 60 > max(c): break
        w = [c[t] for t in range(t0, t0 + win * 60, 60) if t in c]
        o = w[0][1]; lo_ = min(x[3] for x in w); hi = max(x[2] for x in w)
        n += 1; big_dd += (lo_ / o - 1) <= -0.35; big_sw += (hi / lo_ - 1) >= 0.35
    return n, big_dd, big_sw
for name, c, st in (("0", load('ohlcv_1m.json'), 1793240403), ("Lowo", lo, sig_ts)):
    n, dd, sw = windows(c, st)
    print(f"{name}: rolling 15-min windows after entry/signal={n}; drop >=35% from window open: {dd} ({dd/n*100:.0f}%); high/low range >=35%: {sw} ({sw/n*100:.0f}%)")
