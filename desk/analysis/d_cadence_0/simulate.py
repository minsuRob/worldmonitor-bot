"""Book D exit-cadence replay for token "0" (and Lowo) on GeckoTerminal 1-minute OHLCV.
Read-only: uses only files in this folder. Mirrors desk code:
  stop:   last <= entry*(1-0.35)  -> close all          (manual/book_rules.py book_exits)
  TP:     last >= entry*3 -> sell 50%; then trail 40% from peak
  fill:   amm_sell(price, qty*price, liq) = price/(1+value/(liq/2)); fee=max(0.45%*gross, $0.95)  (common.py)
Price seen at a check at time t = close of the last completed 1m candle before t (forward-filled across empty minutes).
"""
import json, datetime as dt, sys
KST = dt.timezone(dt.timedelta(hours=9))
FEE_RATE, FEE_MIN = 0.0045, 0.95
STOP, TP_MULT, TP_FRAC, TRAIL = 0.35, 3.0, 0.5, 0.40

def load(fn):
    L = sorted(json.load(open(fn))['data']['attributes']['ohlcv_list'])
    return {int(r[0]): r for r in L}

def price_at(c, t):
    """close of last completed candle strictly before minute containing t (ffill)."""
    m = (int(t) // 60) * 60 - 60
    while m not in c:
        m -= 60
        if m < min(c): return None
    return c[m][4]

def fee(g): return max(FEE_RATE * g, FEE_MIN)
def sell(qty, px, liq):
    v = qty * px; fpx = px / (1 + v / (liq / 2)); g = qty * fpx; return g - fee(g), fpx

def replay(c, entry_ts, entry_px, qty, cost, liq, interval_s, end_ts, offset=0):
    peak, tp, proceeds, q = entry_px, False, 0.0, qty
    t = entry_ts + offset if offset else entry_ts + interval_s
    while t <= end_ts:
        px = price_at(c, t)
        if px:
            peak = max(peak, px)
            if px <= entry_px * (1 - STOP):
                p, f = sell(q, px, liq); return dict(t=t, px=px, fill=f, rule='STOP', pnl=proceeds + p - cost)
            if tp and px <= peak * (1 - TRAIL):
                p, f = sell(q, px, liq); return dict(t=t, px=px, fill=f, rule='TRAIL', pnl=proceeds + p - cost)
            if not tp and px >= entry_px * TP_MULT:
                p, _ = sell(q * TP_FRAC, px, liq); proceeds += p; q *= (1 - TP_FRAC); tp = True
        t += interval_s
    px = price_at(c, end_ts); p, f = sell(q, px, liq)
    return dict(t=end_ts, px=px, fill=f, rule='OPEN(mark)', pnl=proceeds + p - cost)

def ideal_stop(c, entry_ts, entry_px):
    """continuous watcher: first 1m candle after entry whose LOW crosses the stop; fill at min(open, stop)."""
    lvl = entry_px * (1 - STOP)
    for m in sorted(c):
        if m + 60 <= entry_ts: continue
        o, h, l, cl = c[m][1:5]
        if l <= lvl: return m, min(o, lvl)
    return None, None

fmt = lambda t: dt.datetime.fromtimestamp(t, KST).strftime('%H:%M:%S')

if __name__ == '__main__':
    c = load('ohlcv_1m.json')
    # actual desk position (state/variants/D.db positions id=1, fills id=1/2)
    entry_ts, entry_px, qty, cost = 1793240403.82, 0.00022265102839787835, 220299.90318458102, 50.0
    liq_exit = 30.09296677501377 / ((0.0001366 / 0.00013633581663277463) - 1) * 2   # liq implied by the real exit fill
    end_ts = max(c) + 60
    lvl = entry_px * (1 - STOP)
    print(f"entry {fmt(entry_ts)} KST px {entry_px:.6g}  stop level {lvl:.6g}  TP3x {entry_px*3:.6g}  liq(for exit model) ${liq_exit:,.0f}")
    print("\n-- anchored at entry (first check = entry + interval) --")
    rows = []
    for iv in (1, 2, 5, 10, 15):
        r = replay(c, entry_ts, entry_px, qty, cost, liq_exit, iv * 60, end_ts)
        gap = (r['px'] / lvl - 1) * 100
        print(f"{iv:>3} min  exit {fmt(r['t'])}  seen {r['px']:.4e} ({(r['px']/entry_px-1)*100:+.1f}%)  fill {r['fill']:.4e}  {r['rule']:5}  PnL ${r['pnl']:+.2f}  vs stop level {gap:+.1f}%")
        rows.append(dict(interval_min=iv, **r))
    m, f = ideal_stop(c, entry_ts, entry_px)
    p, ff = sell(qty, f, liq_exit)
    print(f"cont.    exit {fmt(m)}-minute  fill≈{f:.4e} (stop level, candle low crossed)  PnL ${p-cost:+.2f}")
    print("\n-- phase sensitivity: every possible check phase (offset 1..interval min after entry) --")
    for iv in (2, 5, 10, 15, 20, 30):
        res = [replay(c, entry_ts, entry_px, qty, cost, liq_exit, iv * 60, end_ts, offset=o * 60) for o in range(1, iv + 1)]
        pn = [r['pnl'] for r in res]
        print(f"{iv:>3} min  PnL min ${min(pn):+.2f}  median ${sorted(pn)[len(pn)//2]:+.2f}  max ${max(pn):+.2f}   exits: " +
              ", ".join(sorted({fmt(r['t'])[:5] for r in res})))
    print("\n-- actual desk marks (logs/variants.log) --")
    for t in (1793240403, 1793241064, 1793241841, 1793243199):
        px = price_at(c, t); print(f"  {fmt(t)}  gecko last-close {px:.4e} ({(px/entry_px-1)*100:+.1f}%)")
    json.dump(rows, open('results_0.json', 'w'), indent=1)
