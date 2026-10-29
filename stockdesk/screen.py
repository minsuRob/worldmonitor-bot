"""Universe, ban list and the per-slot shared Snapshot every strategy reads (fetch once, cache in market.db).

shared_snapshot(slot, day, market) fetches what the slot needs through quotes.get_source(...) and writes it to
state/market.db; Snapshot then answers only from the DB (asof = slot date, so nothing from the future leaks in).
STOCKDESK_FAKE_SNAPSHOT=1 (config.FAKE_SNAPSHOT) builds a deterministic synthetic market instead (tests, dry runs).
"""
import json, os, random, datetime
import config as C
import marketdb as M
import quotes as Q
import schedule as S
from common import logger

class Snapshot:
    """Read-only view of market.db for one (slot, day, market)."""
    def __init__(self, c, slot, day, market, source="db"):
        self.c, self.slot, self.day, self.market, self.source = c, slot, day, market, source
        self._snap = None; self._flags = None
    def bars(self, code, n, asof=None): return M.get_bars(self.c, self.market, code, n, asof or self.day)
    def flow(self, code, n): return M.get_flow(self.c, self.market, code, n, self.day)
    def snap(self, code):
        if self._snap is None: self._snap = M.get_snap(self.c, self.day, self.slot, self.market)
        return self._snap.get(code)
    def rank(self, key, n=None):
        """Intraday rows sorted by key desc (turnover, change_pct, ...)."""
        if self._snap is None: self._snap = M.get_snap(self.c, self.day, self.slot, self.market)
        rows = sorted((r for r in self._snap.values() if r[key] is not None), key=lambda r: r[key], reverse=True)
        return rows[:n] if n else rows
    def flags(self, code):
        if self._flags is None: self._flags = M.get_flags(self.c, self.market, self.day)
        return self._flags.get(code, [])
    def all_flags(self):
        if self._flags is None: self._flags = M.get_flags(self.c, self.market, self.day)
        return self._flags
    def disclosures(self, book): return M.unjudged_disclosures(self.c, book, self.day)
    def earnings_today(self): return M.earnings_on(self.c, self.market, self.day)
    def fx(self): return M.fx_mark(self.c, self.day)
    def mark(self, code):
        """Price for RISK at this slot: intraday snap price, else the day's close bar, else None."""
        r = self.snap(code)
        if r and r["price"]: return r["price"]
        b = self.bars(code, 1)
        return b[-1]["c"] if b and b[-1]["date"] == self.day else None
    def open_price(self, code):
        r = self.snap(code)
        if r and r["open"]: return r["open"]
        b = self.bars(code, 1)
        return b[-1]["o"] if b and b[-1]["date"] == self.day else None
    def prev_turnover(self, code):
        b = self.bars(code, 2)
        prev = [x for x in b if x["date"] < self.day]
        return prev[-1]["turnover"] if prev else None

def load_universe(c, market):
    rows = M.universe(c, market)
    if rows or market != "US": return rows
    try:
        seed = json.load(open(os.path.join(C.DATA, "us_universe.json")))["rows"]
    except (OSError, KeyError, ValueError): seed = []
    M.put_universe(c, "US", [{**r, "instrument": "STOCK"} for r in seed])
    return M.universe(c, market)

def ban_set(c, market, day):
    """Codes no strategy may buy today: flagged (BAN_FLAGS) + calendar bans (lock-up expiry window)."""
    out = set(M.ban_codes(c, market, day))
    for code, fl in M.get_flags(c, market, day).items():
        if set(fl) & set(C.BAN_FLAGS): out.add(code)
    return out

# ---- fetchers (one per slot; everything they get is written to market.db). Toss spec: quotes.py docstring.
def _refresh_bars(c, toss, market, codes, day, lg):
    """Daily bars: 300 on first sight, else the last 3 (today's partial bar is rewritten until the close)."""
    n_ok = 0
    for code in sorted(codes):
        last = M.get_bars(c, market, code, 1)
        bars, err = toss.daily_bars(market, code, 3 if last else 300)
        if err and not bars: lg.warning(f"toss candles {market} {code}: {err}"); continue
        M.put_bars(c, market, code, _norm_bars(bars), "toss"); n_ok += 1
    return n_ok

def _fill_from_bars(c, market, day, snap):
    """Rankings/prices carry no open/high/low (and /prices no change): take them from today's daily bar."""
    for s in snap:
        b = M.get_bars(c, market, s["code"], 2, day)
        if not b: continue
        last = b[-1]; prev = [x for x in b if x["date"] < day]
        if last["date"] == day:
            s.setdefault("open", None); s.setdefault("high", None); s.setdefault("low", None)
            s["open"] = s["open"] or last["o"]; s["high"] = s["high"] or last["h"]; s["low"] = s["low"] or last["l"]
            if s.get("volume") is None: s["volume"] = last["v"]
        if s.get("change_pct") is None and prev and prev[-1]["c"] and s.get("price"):
            s["change_pct"] = (s["price"] / prev[-1]["c"] - 1) * 100

def _refresh_universe_krx(c, toss, day, held, lg):
    """Once a day: top KRX_UNIVERSE_TOP by 1-month trading amount (+ held), names/type/shares from /stocks, mcap = shares*price."""
    kv = M.KVStore(c)
    if kv.get("universe_day:KRX") == day and M.universe(c, "KRX"): return
    rows, err = toss.rankings("KRX", "turnover", C.KRX_UNIVERSE_TOP, duration="1mo")
    if err and not rows: lg.warning(f"toss universe ranking: {err}"); return
    by = {r["code"]: r for r in rows if r.get("code")}
    codes = sorted(set(by) | set(held))
    info, err = toss.stock_flags_many("KRX", codes, day, with_warnings=False)
    if err: lg.warning(f"toss stocks: {err}")
    out = []
    for code in codes:
        i = info.get(code) or {}; r = by.get(code) or {}
        px = r.get("price"); shares = i.get("shares")
        out.append({"code": code, "name": i.get("name"), "instrument": i.get("instrument") or "STOCK", "sector": i.get("market"),
                    "mcap": shares * px if shares and px else None,
                    "avg_turnover": r["turnover"] / C.KRX_UNIVERSE_TURNOVER_DAYS if r.get("turnover") else None})
    c.execute("DELETE FROM universe WHERE market='KRX'")
    M.put_universe(c, "KRX", out)
    kv["universe_day:KRX"] = day

def _fetch_krx(c, slot, day, held, lg):
    toss = Q.get_source("toss")
    if toss is None:
        lg.info("KRX fetch skipped: Toss credentials not configured"); return "none"
    _refresh_universe_krx(c, toss, day, held, lg)
    uni = [u["code"] for u in M.universe(c, "KRX")]
    rows, err = toss.ranking("KRX", "turnover", 100)
    if err: lg.warning(f"toss ranking: {err}")
    snap = {r["code"]: {"code": r["code"], "price": r["price"], "change_pct": r["change_pct"], "volume": r["volume"], "turnover": r["turnover"],
                        "open": None, "high": None, "low": None, "auction_turnover": None} for r in rows if r.get("code") and r.get("price")}
    rest = [x for x in sorted(set(uni) | set(held)) if x not in snap]
    ps, err = toss.prices(rest) if rest else ({}, None)
    if err: lg.warning(f"toss prices: {err}")
    for code, p in ps.items():
        if p.get("price"): snap[code] = {"code": code, "price": p["price"], "change_pct": None, "volume": None, "turnover": None,
                                         "open": None, "high": None, "low": None, "auction_turnover": None}
    _refresh_bars(c, toss, "KRX", set(snap) | set(held), day, lg)
    snap_rows = list(snap.values()); _fill_from_bars(c, "KRX", day, snap_rows)
    M.put_snap(c, day, slot, "KRX", snap_rows, "toss")
    # flags: /stocks for everything we may hold or buy, /warnings for ranked + held (STOCK group: 5/s published, 4/s used)
    ranked = {r["code"] for r in rows if r.get("code")}
    fl_all, _ = toss.stock_flags_many("KRX", sorted(snap), day, with_warnings=False)
    fl_w, _ = toss.stock_flags_many("KRX", sorted(ranked | set(held)), day, with_warnings=True)
    fl_all.update(fl_w)
    M.put_flags(c, "KRX", day, {code: v["flags"] for code, v in fl_all.items()}, "toss")
    if slot == "krx_after":   # investor flow (net volume -> value at that day's close)
        flow = []
        inst = {u["code"]: u.get("instrument") for u in M.universe(c, "KRX")}
        for code in sorted(set(uni) | set(held)):
            if inst.get(code) not in (None, "STOCK"): continue   # investor flow is for stocks; ETFs/ETNs skipped
            recs, err = toss.investor_flow(code, 5)
            if err: continue
            closes = {b["date"]: b["c"] for b in M.get_bars(c, "KRX", code, 10, day)}
            for r in recs:
                px = closes.get(r["date"])
                if px is None: continue
                v = lambda k: (r[k] * px) if r.get(k) is not None else None
                flow.append({"code": code, "date": r["date"], "foreign_net": v("foreign_net_vol"), "inst_net": v("inst_net_vol"), "retail_net": v("retail_net_vol")})
        if flow: M.put_flow(c, "KRX", flow, "toss")
    fx, err = toss.fx_rate()
    if fx: M.put_fx(c, day, fx, "toss")
    return "toss"

def _fetch_us(c, slot, day, held, lg):
    toss = Q.get_source("toss"); src = "none"
    codes = sorted({r["code"] for r in load_universe(c, "US")} | set(held))
    snap = []
    if toss is not None:
        src = "toss"
        ps, err = toss.prices(codes)
        if err: lg.warning(f"toss prices US: {err}")
        snap = [{"code": k, "price": v["price"], "change_pct": None, "volume": None, "turnover": None, "open": None, "high": None, "low": None,
                 "auction_turnover": None} for k, v in ps.items() if v.get("price")]
        _refresh_bars(c, toss, "US", codes, day, lg)
    else:
        for code in codes:
            last = M.get_bars(c, "US", code, 1)
            if last and last[-1]["date"] >= day: continue
            bars, err = Q.get_source("us_bars").daily_bars(code, 300)
            if err or not bars: lg.warning(f"us bars {code}: {err}"); continue
            M.put_bars(c, "US", code, _norm_bars(bars), "stooq"); src = "stooq"
    if snap:
        _fill_from_bars(c, "US", day, snap); M.put_snap(c, day, slot, "US", snap, src)
    if slot in ("us_close", "us_er"):
        fx = None; fsrc = "toss"
        if toss is not None: fx, _ = toss.fx_rate()
        if not fx: fx, _ = Q.get_source("fx").fx_rate(); fsrc = "erapi"
        if fx: M.put_fx(c, day, fx, fsrc)
        er = Q.get_source("earnings")
        if er is not None:
            rows, err = er.calendar(day, day)
            if rows: M.put_earnings(c, "US", [r for r in rows if r.get("code") in codes], "finnhub")
    return src

def _fetch_dart(c, day, lg):
    dart = Q.get_source("dart")
    if dart is None: lg.info("DART skipped: DART_API_KEY not set"); return 0
    rows, err = dart.list(day)
    if err: lg.warning(f"dart: {err}")
    return M.put_disclosures(c, rows, "dart")

def _norm_bars(rows):
    out = []
    for r in rows:
        try:
            d = str(r["date"]); d = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and "-" not in d else d[:10]
            out.append({"date": d, "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]), "c": float(r["c"]),
                        "v": float(r.get("v") or 0), "turnover": float(r["turnover"]) if r.get("turnover") is not None else float(r["c"]) * float(r.get("v") or 0)})
        except (KeyError, TypeError, ValueError): continue
    return out

def shared_snapshot(slot, day, market, held=(), lg=None):
    """Fetch once for this slot (or build the fake market) and return a Snapshot."""
    lg = lg or logger("screen"); c = M.mdb()
    if C.FAKE_SNAPSHOT:
        fake_market(c, slot, day, market); src = "fake"
    elif market == "KRX":
        src = _fetch_krx(c, slot, day, held, lg)
        if slot == "krx_after": _fetch_dart(c, day, lg)
    else:
        src = _fetch_us(c, slot, day, held, lg)
    return Snapshot(c, slot, day, market, src)

# ---- deterministic fake market (tests, offline dry runs)
FAKE_KRX = [(f"{100000 + i * 1111:06d}", f"가상{i:02d}", 5_000 * (i + 2)) for i in range(40)]

def fake_market(c, slot, day, market, days=320):
    codes = FAKE_KRX if market == "KRX" else [(r["code"], r["name"], 50.0 + 10 * i) for i, r in enumerate(load_universe(c, "US"))]
    if not M.universe(c, market) and market == "KRX":
        M.put_universe(c, "KRX", [{"code": k, "name": n, "instrument": "ETF" if i == 39 else "STOCK", "mcap": 5e11 + i * 1e11,
                                   "avg_turnover": 1e10 + i * 5e8} for i, (k, n, _) in enumerate(codes)])
    end = datetime.date.fromisoformat(day)
    for i, (code, name, px0) in enumerate(codes):
        if M.get_bars(c, market, code, 1, day) and M.get_bars(c, market, code, 1, day)[-1]["date"] == day: continue
        rnd = random.Random(f"{market}:{code}")
        bars, px, d = [], float(px0), end - datetime.timedelta(days=int(days * 1.5))
        drift = 0.0015 if i % 3 == 0 else -0.0005 if i % 3 == 1 else 0.0004
        while d <= end:
            if S.is_trading_day(market, d.isoformat()):
                o = px * (1 + rnd.gauss(0, 0.01)); cl = o * (1 + drift + rnd.gauss(0, 0.02))
                if d == end and i % 7 == 0: cl = o * 1.12            # a few strong closers for CB
                h = max(o, cl) * (1 + abs(rnd.gauss(0, 0.005))); l = min(o, cl) * (1 - abs(rnd.gauss(0, 0.005)))
                v = abs(rnd.gauss(2e6, 5e5)) if market == "KRX" else abs(rnd.gauss(5e6, 1e6))
                if market == "KRX": o, h, l, cl = (float(int(x)) for x in (o, h, l, cl))
                bars.append({"date": d.isoformat(), "o": o, "h": h, "l": l, "c": cl, "v": v, "turnover": cl * v})
                px = cl
            d += datetime.timedelta(days=1)
        M.put_bars(c, market, code, bars, "fake")
        if market == "KRX":
            flow = []
            for b in bars[-30:]:
                f = abs(rnd.gauss(2e9, 5e8)) if i % 5 == 0 else rnd.gauss(0, 1e9)
                flow.append({"code": code, "date": b["date"], "foreign_net": f, "inst_net": f * 0.6, "retail_net": -f * 1.6})
            M.put_flow(c, market, flow, "fake")
    snap = []
    for code, name, _ in codes:
        b = M.get_bars(c, market, code, 2, day)
        if not b or b[-1]["date"] != day: continue
        last, prev = b[-1], (b[-2] if len(b) > 1 else b[-1])
        px = last["c"] * (1.06 if (market == "US" and code == codes[0][0] and slot == "us_er") else 1.0)   # fake after-hours beat reaction
        snap.append({"code": code, "price": px, "open": last["o"], "high": last["h"], "low": last["l"],
                     "change_pct": (last["c"] / prev["c"] - 1) * 100 if prev["c"] else 0.0, "volume": last["v"], "turnover": last["turnover"],
                     "auction_turnover": last["turnover"] * 0.1})
    M.put_snap(c, day, slot, market, snap, "fake")
    if market == "KRX":
        M.put_flags(c, "KRX", day, {codes[1][0]: ["관리종목"], codes[2][0]: ["투자경고"]}, "fake")
        M.put_calendar(c, "KRX", codes[3][0], "LOCKUP_EXPIRY", day, day, day, day, "fake", "fake lock-up expiry")
        M.put_calendar(c, "KRX", codes[4][0], "INDEX_ADD", day, S.next_trading_day("KRX", S.next_trading_day("KRX", day)), None, None, "fake", "fake KOSPI200 add")
        M.put_disclosures(c, [{"rcept_no": f"fake{day.replace('-', '')}0001", "corp_code": "0", "stock_code": codes[5][0], "corp_name": codes[5][1],
                               "report_nm": "단일판매ㆍ공급계약체결", "rcept_dt": day, "flr_nm": codes[5][1], "summary": "계약금액 1,000억원 (매출의 50%)"}], "fake")
        M.put_fx(c, day, 1400.0, "fake")
    else:
        if codes: M.put_earnings(c, "US", [{"code": codes[0][0], "date": day, "when": "amc", "eps_est": 1.0, "eps_act": 1.3, "rev_est": 1e9, "rev_act": 1.1e9}], "fake")
        M.put_fx(c, day, 1400.0, "fake")
