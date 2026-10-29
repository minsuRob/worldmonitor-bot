"""PAPER-ONLY per-book rules for the five independent $1,000 books (BASE, A, B, C, D).

Everything book-specific lives here so run_variants.py stays generic and testable:
  OVERRIDES   config.py values a book changes (applied with run_variants.rules(v))
  PARAMS      book-only parameters that config.py does not have (prechecks, buy rule, exits)
  precheck()  numeric DexScreener checks run BEFORE bots.vet_one (no API calls -> no Helius credits spent on them)
  postcheck() checks that need vet_one's holder count (Helius DAS, already fetched/memoized)
  run30_check() D only: no-chasing check on GeckoTerminal 1-minute candles, last step of D's VET (few calls, throttled, fail closed)
  decide()    turn the Claude JSON into BUY/SKIP with the book's buy rule
  book_exits() per-book stop-loss / partial take-profit / trailing stop, run AFTER the shared RISK pass on its fresh marks
Shared RISK (bots.risk_cycle: UNMEASURABLE close, VOL_RATIO<0.20 close, +60% mcap flag) is identical in every book and
always runs first; book exits only ADD exits, they never skip or loosen RISK. Nothing here places real orders.
"""
import time, json
import config as C
from common import now, amm_sell, fee_for, event

ROUNDTRIP_COST = 0.03   # EV rule cost (A and C)

# ---- D entry filters (2026-10-29, after the token "0" replay in analysis/d_cadence_0: a 0/ZEC pool bought right after a ~3.7x run)
# 1) quote token: D only buys pairs quoted in SOL/WSOL, USDC or USDT (DexScreener pair.quoteToken.address; no API call).
D_QUOTE_ALLOW = {"So11111111111111111111111111111111111111112": "SOL",
                 "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
                 "Es9vMFrzaCERmJfrF8H8B7dGHuJsT5bbGsHq1JsjDAQr": "USDT"}
# 2) no chasing: take the 1-minute candles that started in the last D_RUN30_WINDOW_MIN minutes before the decision time t
#    (start in (t - 30 min, t]); run30 = max over those candles j of high_j / min(low_i over candles i of that window with start_i <= start_j).
#    = the biggest low -> later high rise that happened entirely inside the last 30 minutes (a dip AFTER the top does not count).
#    Reject if run30 >= D_RUN30_MAX_MULT. Candles: GeckoTerminal public 1m OHLCV (USD, base token), fetched ONLY for D candidates
#    that already passed every other D check. Fetch failure / no candles -> fail closed (D_run30_unknown).
D_RUN30_WINDOW_MIN = 30
D_RUN30_MAX_MULT = 2.5
GT_OHLCV_URL = "https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/minute?aggregate=1&limit={limit}&currency=usd"
GT_OHLCV_LIMIT = 40         # 30-minute window + margin (minutes without trades have no candle)
GT_RPS = 0.45               # ~27 calls/min (public limit ~30/min; it returned 429 once on 2026-10-29)
GT_RETRY_SLEEPS = (3.0, 8.0)  # backoff before retry 1 and 2 (429 / 5xx / network error)

OVERRIDES = {
    "BASE": {},
    "A": {},
    "B": {"VET_TOP_HOLDER_MAX": 0.08},                                     # = old C (moved 2026-10-29)
    "C": {"VET_TOP_HOLDER_MAX": 0.08, "VET_H1_ALREADY_PRICED": 150.0,       # momentum rider
          "SIZE_FIXED_FRACTION": 0.10, "MAX_OPEN_POSITIONS": 5},
    "D": {"VET_TOP_HOLDER_MAX": 0.10, "VET_H1_ALREADY_PRICED": 300.0,       # early sniper / lottery
          "SCAN_MIN_LIQ": 5_000.0, "VET_MIN_LIQ": 5_000.0, "SLIPPAGE_BUDGET": 0.04,
          "SIZE_FIXED_FRACTION": 0.05, "MAX_OPEN_POSITIONS": 10},
}

PARAMS = {
    "BASE": {"buy": "claude"},
    "A": {"buy": "ev"},
    "B": {"buy": "claude"},
    "C": {"buy": "ev",
          "pre": {"h1_min": 10.0, "h6_min": 0.0, "m5_min": -8.0, "m5_buys_ge_sells": True},
          "exits": {"stop": 0.20, "tp_mult": 2.0, "tp_frac": 0.50, "trail": 0.25}},
    "D": {"buy": "veto",
          "pre": {"quote_allow": D_QUOTE_ALLOW, "age_min_min": 5.0, "age_max_h": 24.0, "m5_min": -15.0, "m5_buy_sell_ratio": 1.3,
                  "m5_buys_min": 10, "vol_accel_min": 1.2},
          "post": {"holders_min": 50},
          "run30": {"window_min": D_RUN30_WINDOW_MIN, "max_mult": D_RUN30_MAX_MULT},
          "exits": {"stop": 0.35, "tp_mult": 3.0, "tp_frac": 0.50, "trail": 0.40}},
}

# ------------------------------------------------------------------ VET extras
def _num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def precheck(v, p, pair_created, t=None):
    """p = DexScreener pair dict. Returns None (ok) or (check, detail) for a REJECT."""
    pre = PARAMS[v].get("pre")
    if not pre: return None
    t = t or now()
    pc = p.get("priceChange") or {}; tx = p.get("txns") or {}; vol = p.get("volume") or {}
    m5, h1, h6 = _num(pc.get("m5")), _num(pc.get("h1")), _num(pc.get("h6"))
    tm5 = tx.get("m5") or {}; b5, s5 = _num(tm5.get("buys")), _num(tm5.get("sells"))
    if "quote_allow" in pre:
        q = p.get("quoteToken") or {}; qa = q.get("address")
        if qa not in pre["quote_allow"]:
            return (f"{v}_quote_not_sol", f"quote token {q.get('symbol') or '?'} ({qa or 'unknown'}) is not SOL/USDC/USDT")
    if "age_min_min" in pre or "age_max_h" in pre:
        if not pair_created: return (f"{v}_age", "pair age unknown")
        age_m = (t - pair_created) / 60
        if age_m < pre.get("age_min_min", 0): return (f"{v}_age", f"pair age {age_m:.1f}m < {pre['age_min_min']:g}m")
        if age_m > pre.get("age_max_h", 1e9) * 60: return (f"{v}_age", f"pair age {age_m/60:.1f}h > {pre['age_max_h']:g}h (not early)")
    if "h1_min" in pre and h1 < pre["h1_min"]: return (f"{v}_no_momentum", f"priceChange.h1 {h1:g}% < {pre['h1_min']:g}%")
    if "h6_min" in pre and h6 < pre["h6_min"]: return (f"{v}_no_momentum", f"priceChange.h6 {h6:g}% < {pre['h6_min']:g}%")
    if "m5_min" in pre and m5 <= pre["m5_min"]: return (f"{v}_collapsing", f"priceChange.m5 {m5:g}% <= {pre['m5_min']:g}%")
    if pre.get("m5_buys_ge_sells") and b5 < s5: return (f"{v}_sell_pressure", f"m5 buys {b5:.0f} < sells {s5:.0f}")
    if "m5_buys_min" in pre and b5 < pre["m5_buys_min"]: return (f"{v}_inactive", f"m5 buys {b5:.0f} < {pre['m5_buys_min']}")
    if "m5_buy_sell_ratio" in pre:
        r = b5 / s5 if s5 else (99.0 if b5 else 0.0)
        if r < pre["m5_buy_sell_ratio"]: return (f"{v}_buy_ratio", f"m5 buys/sells {r:.2f} < {pre['m5_buy_sell_ratio']:g}")
    if "vol_accel_min" in pre:
        vh1, vm5 = _num(vol.get("h1")), _num(vol.get("m5"))
        acc = vm5 * 12 / vh1 if vh1 else 0.0
        if acc < pre["vol_accel_min"]: return (f"{v}_no_accel", f"volume m5x12/h1 {acc:.2f} < {pre['vol_accel_min']:g}")
    return None

def postcheck(v, holders):
    post = PARAMS[v].get("post")
    if not post: return None
    if "holders_min" in post and holders is not None and holders < post["holders_min"]:
        return (f"{v}_few_holders", f"holders {holders} < {post['holders_min']}")
    return None

# ------------------------------------------------------------------ D no-chasing check (1-minute candles)
def run_multiple(candles, t, window_min=D_RUN30_WINDOW_MIN):
    """candles: [[ts_start, open, high, low, close, volume], ...] in any order (GeckoTerminal ohlcv_list).
    Returns None when no candle started in (t - window, t], else a dict with the run30 multiple and where it came from:
    max over window candles j of high_j / (lowest low of the window candles up to and including j)."""
    w = window_min * 60
    cs = sorted((c for c in candles if c and len(c) >= 5 and _num(c[2]) > 0 and _num(c[3]) > 0), key=lambda c: c[0])
    win = [c for c in cs if t - w < c[0] <= t]
    if not win: return None
    best, lo = None, None
    for j in win:
        if lo is None or _num(j[3]) < _num(lo[3]): lo = j
        m = _num(j[2]) / _num(lo[3])
        if best is None or m > best["multiple"]:
            best = {"multiple": round(m, 3), "high": _num(j[2]), "high_ts": j[0], "low": _num(lo[3]), "low_ts": lo[0]}
    best.update({"candles_window": len(win), "window_min": window_min})
    return best

_OHLCV = {}   # (pool, minute) -> candles, so the same pool is fetched once per cycle
def fetch_ohlcv_1m(pool, lg=None, limit=GT_OHLCV_LIMIT, t=None):
    """GeckoTerminal public 1m OHLCV. Returns (candles or None, note). Throttled (GT_RPS), retries 429/5xx/network errors."""
    import bots   # lazy: bots.http_json is wrapped with call accounting by run_variants
    key = (pool, int((t or time.time()) // 60))
    if key in _OHLCV: return _OHLCV[key], "cached"
    url = GT_OHLCV_URL.format(pool=pool, limit=limit); notes = []
    for attempt in range(len(GT_RETRY_SLEEPS) + 1):
        bots._throttle("geckoterminal", GT_RPS)
        st, j, lat, err = bots.http_json(url, timeout=12)
        if st == 200 and isinstance(j, dict):
            lst = (((j.get("data") or {}).get("attributes") or {}).get("ohlcv_list"))
            if isinstance(lst, list):
                _OHLCV[key] = lst
                return lst, f"geckoterminal 200 ({len(lst)} candles, attempt {attempt + 1})"
            notes.append("200 without ohlcv_list"); break
        notes.append(f"{st} {err}")
        if st is not None and st not in (429,) and st < 500: break   # 4xx other than 429: retrying will not help
        if attempt < len(GT_RETRY_SLEEPS): time.sleep(GT_RETRY_SLEEPS[attempt])
    if lg: lg.warning(f"geckoterminal ohlcv {pool} failed: {notes}")
    return None, "; ".join(notes)

def run30_check(v, pool, t=None, lg=None, fetch=None):
    """D only. Returns (reject or None, info). reject = (check, detail). info goes into the cycle record."""
    cfg = PARAMS[v].get("run30")
    if not cfg: return None, None
    t = t or now(); fetch = fetch or fetch_ohlcv_1m
    try: candles, note = fetch(pool, lg, t=t)
    except Exception as e: candles, note = None, f"{type(e).__name__}: {e}"
    info = {"pool": pool, "source": "geckoterminal ohlcv/minute usd", "note": note, "t": t}
    r = run_multiple(candles, t, cfg["window_min"]) if candles else None
    if r is None:
        info["result"] = "unknown"
        why = f"{note}; no 1m candle in the last {cfg['window_min']} min" if candles else (note or "no candles")
        if lg: lg.warning(f"{v} run30 unknown for pool {pool}: {why} -> reject (fail closed)")
        return (f"{v}_run30_unknown", f"30m run not measurable ({why}); fail closed"), info
    info.update(r)
    if r["multiple"] >= cfg["max_mult"]:
        info["result"] = "reject"
        return (f"{v}_run30_ge_{cfg['max_mult']:g}x",
                f"ran {r['multiple']:.2f}x within 30m (low {r['low']:.4g} -> high {r['high']:.4g}) >= {cfg['max_mult']:g}x: no chasing"), info
    info["result"] = "pass"
    return None, info

# ------------------------------------------------------------------ buy rule
def ev_of(j):
    pw, b = (j or {}).get("p_win"), (j or {}).get("payoff_ratio")
    if isinstance(pw, (int, float)) and isinstance(b, (int, float)): return pw * b - (1 - pw) - ROUNDTRIP_COST
    return None

def decide(v, j):
    """Returns (decision, rule_text, ev). j = parsed Claude JSON (None -> SKIP)."""
    ev = ev_of(j)
    mode = PARAMS[v]["buy"]
    if mode == "ev":
        dec = "BUY" if (ev is not None and ev > 0) else "SKIP"
        return dec, (f"EV p*b-(1-p)-{ROUNDTRIP_COST} = {ev:.4f}" if ev is not None else "EV not computable"), ev
    if mode == "veto":
        if not j: return "SKIP", "no veto answer", ev
        return ("BUY", "numeric signal, no Claude veto", ev) if j.get("decision") == "BUY" else ("SKIP", "Claude veto", ev)
    return ("BUY" if (j or {}).get("decision") == "BUY" else "SKIP"), "claude decision", ev

# ------------------------------------------------------------------ exits (per book, after shared RISK)
EXTRA_SQL = """CREATE TABLE IF NOT EXISTS vexit (position_id INTEGER PRIMARY KEY, tp_done INTEGER DEFAULT 0, partial_proceeds REAL DEFAULT 0,
  partial_cost REAL DEFAULT 0, partial_qty REAL DEFAULT 0, ts REAL);"""

def partial_sell(c, pos, frac, price, liq, rule, detail):
    """Sell frac of an OPEN meme position at the RISK mark (same AMM + fee model as bots.close_position)."""
    qs = pos["qty"] * frac; cost_part = (pos["cost_usd"] or 0) * frac
    value = qs * price
    exit_px = amm_sell(price, value, liq) if liq else price
    gross = qs * exit_px; fee = fee_for(gross) if gross > 0 else 0
    proceeds = max(gross - fee, 0.0)
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute("UPDATE positions SET qty=qty-?, cost_usd=cost_usd-? WHERE id=? AND status='OPEN'", (qs, cost_part, pos["id"]))
        c.execute("UPDATE account SET cash=cash+? WHERE id=1", (proceeds,))
        c.execute("""INSERT INTO fills (ts,position_id,action,token,symbol,requested_usd,filled_usd,partial,expected_price,fill_price,slippage_bps,fee,qty,over_limit,detail)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (now(), pos["id"], "SELL_PARTIAL", pos["token"], pos["symbol"], value, proceeds, 1, price, exit_px,
                     (exit_px - price) / price * 1e4 if price else 0, fee, qs, int(price and abs(exit_px - price) / price > C.SLIPPAGE_LIMIT), rule))
        c.execute("""INSERT INTO vexit (position_id,tp_done,partial_proceeds,partial_cost,partial_qty,ts) VALUES (?,1,?,?,?,?)
                     ON CONFLICT(position_id) DO UPDATE SET tp_done=1, partial_proceeds=partial_proceeds+excluded.partial_proceeds,
                     partial_cost=partial_cost+excluded.partial_cost, partial_qty=partial_qty+excluded.partial_qty, ts=excluded.ts""",
                  (pos["id"], proceeds, cost_part, qs, now()))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK"); raise
    event(c, "risk", "PARTIAL_TP", {"position": pos["id"], "symbol": pos["symbol"], "rule": rule, "detail": detail})
    return proceeds

def _fold_partial(c, pos_id):
    """After a full close, realized_pnl covers the remaining part only; add the partial-sale PnL."""
    r = c.execute("SELECT partial_proceeds, partial_cost FROM vexit WHERE position_id=?", (pos_id,)).fetchone()
    if r: c.execute("UPDATE positions SET realized_pnl=COALESCE(realized_pnl,0)+?, proceeds_usd=COALESCE(proceeds_usd,0)+?, "
                    "cost_usd=cost_usd+? WHERE id=?", (r[0] - r[1], r[0], r[1], pos_id))

def book_exits(c, v, lg, close_position, liq_of=None):
    """Per-book exits on the marks the shared RISK pass just wrote (no new API calls).
    liq_of(pos) -> current liquidity for the AMM exit model (defaults to entry_liq)."""
    ex = PARAMS[v].get("exits")
    out = []
    if not ex: return out
    c.executescript(EXTRA_SQL)
    for pos in c.execute("SELECT * FROM positions WHERE status='OPEN' AND kind='meme'").fetchall():
        px, entry, peak = pos["last_price"], pos["entry_price"], pos["peak_price"] or pos["entry_price"]
        if not px or not entry: continue
        liq = (liq_of(pos) if liq_of else None) or pos["entry_liq"]
        st = c.execute("SELECT tp_done FROM vexit WHERE position_id=?", (pos["id"],)).fetchone()
        tp_done = bool(st and st[0])
        if px <= entry * (1 - ex["stop"]):
            rule = f"{v}_STOP_-{ex['stop']*100:.0f}%"
            close_position(c, dict(pos), px, liq, rule, f"last {px} <= entry {entry} x {1-ex['stop']:.2f}")
            _fold_partial(c, pos["id"]); out.append((pos["symbol"], rule)); continue
        if tp_done and px <= peak * (1 - ex["trail"]):
            rule = f"{v}_TRAIL_-{ex['trail']*100:.0f}%_FROM_PEAK"
            close_position(c, dict(pos), px, liq, rule, f"last {px} <= peak {peak} x {1-ex['trail']:.2f} after partial TP")
            _fold_partial(c, pos["id"]); out.append((pos["symbol"], rule)); continue
        if not tp_done and px >= entry * ex["tp_mult"]:
            rule = f"{v}_TP_{ex['tp_frac']*100:.0f}%_AT_{ex['tp_mult']:g}x"
            partial_sell(c, dict(pos), ex["tp_frac"], px, liq, rule, f"last {px} >= entry {entry} x {ex['tp_mult']:g}")
            out.append((pos["symbol"], rule))
    if out and lg: lg.info(f"book exits {v}: {out}")
    return out

# ------------------------------------------------------------------ plain-words rules for the judge prompt / README
def describe(v):
    """Book-specific sentence (diff vs BASE + buy rule + exits). Numbers come from OVERRIDES/PARAMS."""
    o, p = OVERRIDES[v], PARAMS[v]
    if v == "BASE": diff = "Baseline book."
    elif v == "A": diff = "Differs from BASE only in the buy rule."
    elif v == "B": diff = "Differs from BASE: largest-holder limit 8% (BASE 5%)."
    elif v == "C":
        pr = p["pre"]
        diff = (f"AGGRESSIVE MOMENTUM RIDER: buys tokens that are ALREADY moving and tries to ride the continuation. Requires 1h price change >= {pr['h1_min']:g}% "
                f"and < {o['VET_H1_ALREADY_PRICED']:g}% (blow-offs rejected), 6h change >= {pr['h6_min']:g}%, 5m change > {pr['m5_min']:g}% (not collapsing), "
                f"5m buys >= sells; largest holder <= {o['VET_TOP_HOLDER_MAX']*100:.0f}%. Size: fixed {o['SIZE_FIXED_FRACTION']*100:.0f}% of equity, "
                f"max {o['MAX_OPEN_POSITIONS']} open positions.")
    elif v == "D":
        pr, po = p["pre"], p["post"]
        diff = (f"AGGRESSIVE EARLY SNIPER / LOTTERY: young pairs aged {pr['age_min_min']:g} min to {pr['age_max_h']:g} h, liquidity >= ${o['VET_MIN_LIQ']:,.0f}, "
                f"largest holder <= {o['VET_TOP_HOLDER_MAX']*100:.0f}%, >= {po['holders_min']} holders, numeric entry signal: 5m buys/sells >= {pr['m5_buy_sell_ratio']:g} "
                f"with >= {pr['m5_buys_min']} buys, 5m volume pace >= {pr['vol_accel_min']:g}x the 1h pace, 5m change > {pr['m5_min']:g}%, 1h change < {o['VET_H1_ALREADY_PRICED']:g}%; "
                f"quote token SOL/USDC/USDT only; no chasing: not bought after a >= {p['run30']['max_mult']:g}x run within {p['run30']['window_min']:g} minutes (1-minute candles). "
                f"Size: fixed {o['SIZE_FIXED_FRACTION']*100:.0f}% of equity (many small tickets), max {o['MAX_OPEN_POSITIONS']} open positions, "
                f"{o['SLIPPAGE_BUDGET']*100:.0f}% round-trip slippage budget. Expects many small losses and rare large winners.")
    buy = {"claude": "Buy rule: the book buys if you answer BUY.",
           "ev": f"Buy rule: this book IGNORES your BUY/SKIP word and buys only if p_win*payoff_ratio - (1-p_win) - {ROUNDTRIP_COST} > 0 using your numbers, so calibrate them"
                 + (" to THIS book's exit plan." if p.get("exits") else "."),   # A keeps its original wording
           "veto": "Buy rule: the numeric signal already fired; you are a VETO only. Answer SKIP only for clear rug/scam red flags; otherwise BUY."}[p["buy"]]
    ex = p.get("exits")
    exits = ("Exits: the desk's shared RISK rules" + (f" plus this book's own: stop-loss at -{ex['stop']*100:.0f}% from entry, sell {ex['tp_frac']*100:.0f}% at "
             f"{ex['tp_mult']:g}x entry, then trailing stop {ex['trail']*100:.0f}% below the peak on the rest." if ex else ", same in every book."))
    return diff, buy, exits

D_SYSTEM = """You are the RUG VETO for ONE paper book of a PAPER-ONLY (simulated) Solana memecoin desk. No real money is involved.
This book (D, "early sniper / lottery") deliberately buys very young tokens on numeric momentum signals with small fixed tickets. It EXPECTS most trades to lose (stop-loss -35%) and relies on rare large winners (partial take-profit at 3x, wide trailing stop). Being speculative, young, thin or unproven is NOT a reason to veto here.
Your only job: veto (SKIP) when the data shows a CLEAR rug/scam/manipulation red flag, for example: liquidity tiny vs market cap or being pulled, one wallet or a few wallets holding most of the supply, buys with almost no sells (possible honeypot), wash-trade-looking volume vs very few holders, price already collapsing hard, or an obvious copycat of a just-rugged token. Otherwise answer BUY.
Return ONLY one JSON object, no prose, exactly:
{"decision":"BUY"|"SKIP","confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}
decision BUY = no veto, SKIP = veto. Still give honest p_win (probability of reaching +200% before -35% over ~24h) and payoff_ratio (average win / average loss under this exit plan)."""
