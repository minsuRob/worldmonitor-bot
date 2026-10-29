"""Minimal daily-bar backtester for numeric books (FL, MO, MO-US) and a daily-bar approximation of CB, using the SAME
strategy screens and the SAME fills/costs as the live books. Reads state/market.db (bars_daily, flow_daily, universe).

  python3 backtest/bt.py <CODE> <YYYY-MM-DD from> <YYYY-MM-DD to> [--fake]

Limits (also in backtest/README.md): no LLM (LLM books are skipped or treated as buy-all), CB uses the daily close as the
auction price and the day's turnover as the ranking key (no 15:00 intraday snapshot), flags/bans only where market.db has
them. The DataView only answers rows dated <= the simulated day, so nothing from the future leaks in.
"""
import os, sys, json, tempfile, datetime
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
if "--fake" in sys.argv:
    os.environ["STOCKDESK_FAKE_SNAPSHOT"] = "1"
import config as C
if "--fake" in sys.argv:   # keep the real ledgers and cache untouched
    tmp = tempfile.mkdtemp(prefix="stockdesk-bt-"); C.MARKET_DB = os.path.join(tmp, "market.db")
import marketdb as M
import schedule as S
import screen as SC
import fills as F
import strategies
from strategies.base import Ctx

class DataView(SC.Snapshot):
    """Snapshot answering from daily bars only, as of `day` (the intraday table is replaced by that day's bar)."""
    def snap(self, code):
        b = M.get_bars(self.c, self.market, code, 2, self.day)
        if not b or b[-1]["date"] != self.day: return None
        last, prev = b[-1], (b[-2] if len(b) > 1 else b[-1])
        return {"code": code, "price": last["c"], "open": last["o"], "high": last["h"], "low": last["l"], "volume": last["v"], "turnover": last["turnover"],
                "auction_turnover": None, "change_pct": (last["c"] / prev["c"] - 1) * 100 if prev["c"] else 0.0, "high20": None, "name": ""}
    def rank(self, key, n=None):
        rows = [r for r in (self.snap(u["code"]) for u in M.universe(self.c, self.market)) if r and r.get(key) is not None]
        rows.sort(key=lambda r: r[key], reverse=True)
        return rows[:n] if n else rows

def run(code, d_from, d_to):
    st = strategies.by_code(code)
    if st.needs_llm and code != "CB": sys.exit(f"{code} needs an LLM judgment; backtest supports numeric books and CB (veto skipped)")
    c = M.mdb(); market = st.market
    cash = C.START_BALANCE_KRW if market == "KRX" else C.START_BALANCE_USD
    start = cash; pos = {}; pending = []; curve = []; trades = []
    if C.FAKE_SNAPSHOT: SC.fake_market(c, "bt", d_to, market)   # one synthetic history up to d_to; the DataView hides later rows
    day = d_from if S.is_trading_day(market, d_from) else S.next_trading_day(market, d_from)
    while day <= d_to:
        view = DataView(c, "bt", day, market, "bt")
        # 1) fills at today's open for yesterday's decisions, 2) exits at today's open, 3) screen at today's close
        for p in list(pos.values()):
            ex = st.exits(p, view.mark(p["code"]), Ctx("bt", day, 0, market, view, M.universe(c, market), set()))
            if ex:
                o = view.open_price(p["code"]) or view.mark(p["code"])
                if o is None: continue
                f = F.fill_open(market, "SELL", p["qty"], o, None, p["instrument"])
                proceeds = f["value"] - f["fee"] - f["tax"] - f["other"]; cash += proceeds
                trades.append({"code": p["code"], "entry_day": p["entry_day"], "exit_day": day, "pnl": proceeds - p["cost"], "rule": ex})
                del pos[p["code"]]
        for o in pending:
            if o["code"] in pos: continue
            if o["kind"] == "CLOSE_AUCTION": continue
            f = F.fill_open(market, "BUY", min(o["value"], cash), view.open_price(o["code"]), view.prev_turnover(o["code"]), o["instrument"])
            if f["status"] not in ("FILLED", "PARTIAL"): continue
            total = f["value"] + f["fee"] + f["tax"] + f["other"]; cash -= total
            pos[o["code"]] = {"id": 0, "code": o["code"], "market": market, "qty": f["qty"], "entry_price": f["price"], "peak_price": f["price"], "cost": total,
                              "hold_days": 0, "entry_day": day, "signal_json": json.dumps(o["signal"], default=str), "instrument": o["instrument"], "status": "OPEN"}
        pending = []
        for p in pos.values():
            m = view.mark(p["code"])
            if m: p["peak_price"] = max(p["peak_price"], m); p["hold_days"] += 1; p["last"] = m
        ctx = Ctx("bt", day, 0, market, view, SC.load_universe(c, market), SC.ban_set(c, market, day))
        eq = cash + sum(p["qty"] * p.get("last", p["entry_price"]) for p in pos.values())
        for cand in st.screen(ctx):
            if cand.code in ctx.ban or cand.code in pos: continue
            if st.max_open() and len(pos) + len(pending) >= st.max_open(): break
            value = min(st.size(eq, cand), C.MAX_POSITION_PCT * eq)
            kind, _ = st.order_kind(cand)
            if kind == "CLOSE_AUCTION":   # CB: buy at today's close now, sell at the next open (exits)
                f = F.fill_close_auction(market, min(value, cash), view.mark(cand.code), None, (view.snap(cand.code) or {}).get("turnover"), cand.instrument)
                if f["status"] in ("FILLED", "PARTIAL"):
                    total = f["value"] + f["fee"] + f["tax"] + f["other"]; cash -= total
                    pos[cand.code] = {"id": 0, "code": cand.code, "market": market, "qty": f["qty"], "entry_price": f["price"], "peak_price": f["price"], "cost": total,
                                      "hold_days": 0, "entry_day": day, "signal_json": "{}", "instrument": cand.instrument, "status": "OPEN", "last": f["price"]}
            else:
                pending.append({"code": cand.code, "value": value, "kind": kind, "instrument": cand.instrument, "signal": cand.screen_json})
        eq = cash + sum(p["qty"] * p.get("last", p["entry_price"]) for p in pos.values())
        curve.append((day, eq))
        day = S.next_trading_day(market, day)
    peak, mdd = start, 0.0
    for _, e in curve: peak = max(peak, e); mdd = max(mdd, (peak - e) / peak)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    out = {"book": code, "from": d_from, "to": d_to, "days": len(curve), "start": round(start, 2), "end": round(curve[-1][1], 2) if curve else start,
           "return_pct": round((curve[-1][1] / start - 1) * 100, 2) if curve else 0.0, "mdd_pct": round(mdd * 100, 2), "trades": len(trades),
           "win_rate": round(wins / len(trades), 3) if trades else None, "open_at_end": len(pos), "data": "fake" if C.FAKE_SNAPSHOT else "market.db"}
    return out, curve, trades

if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(a) != 3: sys.exit(__doc__)
    out, curve, trades = run(*a)
    print(json.dumps(out, ensure_ascii=False))
