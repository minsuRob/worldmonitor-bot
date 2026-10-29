"""READ-ONLY market data adapters. PAPER ONLY.

TossQuotes talks to the Toss Securities Open API for QUOTES ONLY: the OAuth2 client-credentials token and
market-data / stock-info / market-info / ranking GETs. There are no order, account, holdings, buying-power or
commission methods; the path allowlist (ALLOWED_PATHS, path templates) and FORBIDDEN_WORDS refuse anything else and
manual/tests/test_toss_readonly.py enforces both.

Source of truth (checked 2026-10-29): https://openapi.tossinvest.com/openapi-docs/latest/openapi.json and
openapi-docs/overview.md. Success bodies are {"result": ...}, every number is a string, errors are
{"error": {code, message, requestId}}, 429 carries Retry-After. ONE valid token per client: issuing a new one revokes
the old one, so the token is cached in a shared store (market.db kv) instead of per process.
Public fallbacks (DART, Stooq, er-api, Finnhub) keep the desk running when Toss credentials are absent.
"""
import csv, io, json, re, threading, time
import config as C
from common import http_json, http_text, now, kst_day

FORBIDDEN_WORDS = ("order", "account", "holding", "balance", "buying-power", "sellable", "commission", "cancel",
                   "deposit", "withdraw", "transfer", "conditional")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-]{1,20}$")

# ---- Toss endpoint table (official spec). Paths may hold {symbol}; it is validated with SYMBOL_RE before substitution.
TOSS_ENDPOINTS = {
    "token":          {"method": "POST", "path": "/oauth2/token", "group": "AUTH"},
    "prices":         {"method": "GET", "path": "/api/v1/prices", "group": "MARKET_DATA"},                    # symbols<=200
    "candles":        {"method": "GET", "path": "/api/v1/candles", "group": "MARKET_DATA_CHART"},             # symbol, interval 1d|1m, count<=200, before
    "stocks":         {"method": "GET", "path": "/api/v1/stocks", "group": "STOCK"},                          # symbols<=200
    "warnings":       {"method": "GET", "path": "/api/v1/stocks/{symbol}/warnings", "group": "STOCK"},
    "investor_flow":  {"method": "GET", "path": "/api/v1/stocks/{symbol}/investor-trading", "group": "STOCK_TRADING_TREND"},   # KR only, count<=100
    "rankings":       {"method": "GET", "path": "/api/v1/rankings", "group": "RANKING"},                      # type, marketCountry, duration, count<=100
    "exchange_rate":  {"method": "GET", "path": "/api/v1/exchange-rate", "group": "MARKET_INFO"},
    "calendar_kr":    {"method": "GET", "path": "/api/v1/market-calendar/KR", "group": "MARKET_INFO"},
    "calendar_us":    {"method": "GET", "path": "/api/v1/market-calendar/US", "group": "MARKET_INFO"},
}
ALLOWED_PATHS = tuple(sorted({e["path"] for e in TOSS_ENDPOINTS.values()}))
RANK_TYPES = {"turnover": ("MARKET_TRADING_AMOUNT", "realtime"), "volume": ("MARKET_TRADING_VOLUME", "realtime"),
              "change_pct": ("TOP_GAINERS", "1d"), "gainers": ("TOP_GAINERS", "1d"), "losers": ("TOP_LOSERS", "1d")}
COUNTRY = {"KRX": "KR", "US": "US"}
# Toss warning / status -> desk flag names (config.HALT_FLAGS / BAN_FLAGS). 관리종목·불성실공시 are not in the Toss API.
WARNING_FLAGS = {"LIQUIDATION_TRADING": "정리매매", "OVERHEATED": "단기과열", "INVESTMENT_WARNING": "투자경고", "INVESTMENT_RISK": "투자위험"}

def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def _day(ts):
    return str(ts)[:10] if ts else None


class RateLimiter:
    """Per-group request spacing (requests per second). Pattern: desk/bots.py _throttle."""
    def __init__(self, rps_by_group):
        self.rps = dict(rps_by_group); self.last = {}; self.lock = threading.Lock()
    def wait(self, group, sleep=time.sleep):
        with self.lock:
            gap = 1.0 / self.rps.get(group, 1.0)
            t = time.monotonic(); last = self.last.get(group, 0.0)
            delay = max(0.0, last + gap - t)
            self.last[group] = max(t, last + gap)
        if delay > 0: sleep(delay)
        return delay


class TossQuotes:
    """Quotes-only Toss client. `store` is a dict-like token cache (pass marketdb.KVStore to share it across processes)."""
    def __init__(self, client_id=None, client_secret=None, store=None, limiter=None, http=None, sleep=time.sleep):
        self.client_id = client_id if client_id is not None else C.TOSS_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else C.TOSS_CLIENT_SECRET
        self.store = store if store is not None else {}
        self.limiter = limiter or RateLimiter(C.TOSS_RPS)
        self.http = http or http_json
        self.sleep = sleep
        self.calls = 0

    def configured(self): return bool(self.client_id and self.client_secret)

    def _token(self, force=False):
        tok = self.store.get("toss_token")
        if tok and not force and tok.get("expires_ts", 0) - C.TOSS_TOKEN_MARGIN_S > now():
            return tok["access"]
        e = TOSS_ENDPOINTS["token"]
        self.limiter.wait(e["group"], self.sleep)
        st, j, _, err = self.http(C.TOSS_BASE + e["path"], method="POST",
                                  form={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
        self.calls += 1
        if st != 200 or not isinstance(j, dict) or "access_token" not in j:
            code = ((j or {}).get("error") or {}).get("code") if isinstance(j, dict) else None
            raise RuntimeError(f"toss token failed: HTTP {st} {code or err or ''}".strip())
        tok = {"access": j["access_token"], "expires_ts": now() + float(j.get("expires_in", 3600))}
        self.store["toss_token"] = tok
        return tok["access"]

    def _get(self, name, symbol=None, **params):
        """GET one endpoint -> (result, err). Only allowlisted GET paths; {symbol} validated before substitution."""
        e = TOSS_ENDPOINTS[name]
        assert e["method"] == "GET", f"{name}: quotes client only GETs"
        assert e["path"] in ALLOWED_PATHS, f"{name}: path not in allowlist"
        assert not any(w in e["path"].lower() for w in FORBIDDEN_WORDS), f"{name}: forbidden path"
        path = e["path"]
        if symbol is not None or "{symbol}" in path:
            assert symbol is not None and SYMBOL_RE.match(str(symbol)), f"{name}: bad symbol {symbol!r}"
            if "{symbol}" in path: path = path.replace("{symbol}", str(symbol))
            else: params = {"symbol": symbol, **params}          # /candles takes symbol as a query parameter
        q = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        for p in params.values():
            assert p is None or re.match(r"^[A-Za-z0-9_.,:+\-]{0,4000}$", str(p)), f"{name}: bad query value"
        url = C.TOSS_BASE + path + (f"?{q}" if q else "")
        refreshed = retried = False; force = False
        while True:
            self.limiter.wait(e["group"], self.sleep)
            st, j, _, err = self.http(url, headers={"Authorization": "Bearer " + self._token(force=force)})
            force = False
            self.calls += 1
            if st == 401 and not refreshed:
                refreshed = force = True; continue
            if st == 429 and not retried:   # http_json does not expose headers; Retry-After is short for per-second limits
                retried = True; self.sleep(C.TOSS_429_WAIT_S); continue
            if st != 200 or not isinstance(j, dict):
                code = ((j or {}).get("error") or {}).get("code") if isinstance(j, dict) else None
                return None, f"HTTP {st} {code or err or ''}".strip()
            return j.get("result"), None

    # ---- raw endpoints (normalized)
    def prices(self, symbols):
        out = {}
        for i in range(0, len(symbols), 200):
            r, err = self._get("prices", symbols=",".join(symbols[i:i + 200]))
            if err: return out, err
            for x in r or []:
                out[x.get("symbol")] = {"price": _f(x.get("lastPrice")), "ts": x.get("timestamp"), "currency": x.get("currency")}
        return out, None

    def candles(self, code, interval="1d", n=100, before=None):
        """Oldest first. Paginates with nextBefore up to n rows."""
        rows, seen, nb, err = [], set(), before, None   # rows newest first, as the API returns them
        while len(rows) < n:
            r, err = self._get("candles", symbol=code, interval=interval, count=min(200, n - len(rows) + (1 if nb else 0)), before=nb)
            if err: break
            cs = (r or {}).get("candles") or []
            fresh = 0
            for x in cs:
                ts = x.get("timestamp")
                if ts in seen: continue          # `before` is inclusive: the cursor candle repeats on the next page
                seen.add(ts); fresh += 1
                rows.append({"ts": ts, "date": _day(ts), "o": _f(x.get("openPrice")), "h": _f(x.get("highPrice")), "l": _f(x.get("lowPrice")),
                             "c": _f(x.get("closePrice")), "v": _f(x.get("volume")) or 0.0, "turnover": None})
            nb = (r or {}).get("nextBefore")
            if not fresh or not nb: break
        return list(reversed(rows[:n])), (err if not rows else None)

    def stocks(self, symbols):
        out = {}
        for i in range(0, len(symbols), 200):
            r, err = self._get("stocks", symbols=",".join(symbols[i:i + 200]))
            if err: return out, err
            for x in r or []: out[x.get("symbol")] = x
        return out, None

    def warnings(self, code, day=None):
        """Active warnings as Toss codes (start <= day <= end, end null = open)."""
        r, err = self._get("warnings", symbol=code)
        if err: return [], err
        day = day or kst_day(); act = []
        for w in r or []:
            s, e = w.get("startDate"), w.get("endDate")
            if (s is None or s <= day) and (e is None or e >= day): act.append(w.get("warningType"))
        return act, None

    def investor_flow(self, code, n=10):
        """KR investor trading, oldest first: {date, foreign_net, inst_net, retail_net} as NET VOLUME (shares)."""
        r, err = self._get("investor_flow", symbol=code, count=min(100, n))
        if err: return [], err
        out = []
        for x in (r or {}).get("records") or []:
            g = lambda k: _f(((x.get(k) or {}).get("netBuyVolume")))
            out.append({"code": code, "date": x.get("date"), "foreign_net_vol": g("foreigner"), "inst_net_vol": g("institution"), "retail_net_vol": g("individual")})
        return list(reversed(out)), None

    def rankings(self, market, key, n=100, exclude_caution=False, duration=None):
        typ, dur = RANK_TYPES[key]
        dur = duration or dur
        r, err = self._get("rankings", type=typ, marketCountry=COUNTRY[market], duration=dur, count=min(100, n),
                           excludeInvestmentCaution="true" if exclude_caution else None)
        if err: return [], err
        out = []
        for x in (r or {}).get("rankings") or []:
            p = x.get("price") or {}
            cr = _f(p.get("changeRate"))
            out.append({"code": x.get("symbol"), "rank": x.get("rank"), "price": _f(p.get("lastPrice")), "base_price": _f(p.get("basePrice")),
                        "change_pct": cr * 100 if cr is not None else None, "volume": _f(x.get("tradingVolume")), "turnover": _f(x.get("tradingAmount")),
                        "ranked_at": (r or {}).get("rankedAt")})
        return out, None

    def exchange_rate(self):
        r, err = self._get("exchange_rate", baseCurrency="USD", quoteCurrency="KRW")
        if err: return None, err
        return {"rate": _f((r or {}).get("rate")), "mid": _f((r or {}).get("midRate")), "valid_from": (r or {}).get("validFrom")}, None

    # ---- contract used by screen.py
    def quote(self, market, code):
        """price from /prices; open/high/low/volume/change from today's 1d candle and the previous close. turnover None (not in the API)."""
        ps, err = self.prices([code])
        if err or code not in ps: return None, err or "no price"
        bars, err2 = self.candles(code, "1d", 2)
        q = {"price": ps[code]["price"], "ts": ps[code]["ts"], "open": None, "high": None, "low": None, "volume": None, "turnover": None, "change_pct": None}
        if bars:
            last = bars[-1]
            if last["date"] == _day(ps[code]["ts"]):
                q.update(open=last["o"], high=last["h"], low=last["l"], volume=last["v"])
                prev = bars[-2]["c"] if len(bars) > 1 else None
            else:
                prev = last["c"]
            if prev and q["price"]: q["change_pct"] = (q["price"] / prev - 1) * 100
        return q, None

    def daily_bars(self, market, code, n):
        return self.candles(code, "1d", n)

    def minute_bars(self, market, code, date=None):
        rows, err = self.candles(code, "1m", 200)
        return ([r for r in rows if not date or r["date"] == date], err)

    def ranking(self, market, key, n):
        return self.rankings(market, key, n)

    def stock_flags_many(self, market, codes, day=None, with_warnings=True):
        """{code: {"name","instrument","market","shares","flags":[desk flag names]}} using /stocks (200 per call) + /warnings per code."""
        info, err = self.stocks(list(codes))
        out = {}
        for code in codes:
            x = info.get(code)
            if not x: continue
            kmd = x.get("koreanMarketDetail") or {}
            fl = set()
            if kmd.get("krxTradingSuspended"): fl.add("거래정지")
            if kmd.get("liquidationTrading"): fl.add("정리매매")
            if x.get("status") == "DELISTED": fl.add("상장폐지")
            if with_warnings:
                ws, _ = self.warnings(code, day)
                fl |= {WARNING_FLAGS[w] for w in ws if w in WARNING_FLAGS}
            st = x.get("securityType") or "STOCK"
            out[code] = {"name": x.get("name"), "instrument": "ETF" if st in ("ETF", "FOREIGN_ETF") else ("STOCK" if st in ("STOCK", "FOREIGN_STOCK") else st),
                         "market": x.get("market"), "shares": _f(x.get("sharesOutstanding")), "flags": sorted(fl)}
        return out, err

    def stock_flags(self, market, code):
        m, err = self.stock_flags_many(market, [code])
        return (m.get(code), err) if m.get(code) else (None, err or "unknown symbol")

    def fx_rate(self):
        """USD/KRW mid rate (매매기준율) for marks; conversion cost is config.FX_CONVERSION_COST."""
        r, err = self.exchange_rate()
        if err or not r: return None, err or "no fx"
        return (r["mid"] or r["rate"]), None


# ---- public fallbacks (all TBC unless noted)
class DartOpen:
    """DART Open API list.json (format confirmed from public docs). Needs DART_API_KEY."""
    def __init__(self, key=None, http=None):
        self.key = key if key is not None else C.DART_API_KEY
        self.http = http or http_json
    def configured(self): return bool(self.key)
    def list(self, date, page_count=100, max_pages=10):
        """All disclosures of one day (YYYY-MM-DD). Returns (rows, err). Rows keep DART field names + summary=''."""
        d = date.replace("-", ""); out = []
        for page in range(1, max_pages + 1):
            url = (f"{C.DART_BASE}/list.json?crtfc_key={self.key}&bgn_de={d}&end_de={d}&page_no={page}&page_count={page_count}")
            st, j, _, err = self.http(url)
            if st != 200 or not isinstance(j, dict): return out, f"dart HTTP {st} {err or ''}".strip()
            if j.get("status") not in ("000", "013"): return out, f"dart status {j.get('status')} {j.get('message','')}"
            for it in j.get("list", []):
                it = dict(it); it["summary"] = ""; it["rcept_dt"] = f"{it['rcept_dt'][:4]}-{it['rcept_dt'][4:6]}-{it['rcept_dt'][6:]}"
                out.append(it)
            if page >= int(j.get("total_page", 1) or 1): break
        return out, None


class UsDailyBars:
    """Stooq daily CSV (TBC: unofficial, daily call cap). Date,Open,High,Low,Close,Volume."""
    def __init__(self, http=None): self.http = http or http_text
    def daily_bars(self, code, n=300):
        st, txt, _, err = self.http(C.STOOQ_DAILY.format(sym=code.lower()))
        if st != 200 or not txt: return [], f"stooq HTTP {st} {err or ''}".strip()
        rows = []
        for r in csv.DictReader(io.StringIO(txt)):
            try:
                rows.append({"date": r["Date"], "o": float(r["Open"]), "h": float(r["High"]), "l": float(r["Low"]), "c": float(r["Close"]),
                             "v": float(r["Volume"] or 0), "turnover": float(r["Close"]) * float(r["Volume"] or 0)})
            except (KeyError, ValueError): continue
        return rows[-n:], None


class FxPublic:
    """open.er-api.com USD base (TBC: unofficial free endpoint)."""
    def __init__(self, http=None): self.http = http or http_json
    def fx_rate(self):
        st, j, _, err = self.http(C.ERAPI_FX)
        try: return float(j["rates"]["KRW"]), None
        except (TypeError, KeyError, ValueError): return None, f"erapi HTTP {st} {err or ''}".strip()


class FinnhubEarnings:
    """Finnhub earnings calendar (TBC; FINNHUB_API_KEY optional)."""
    def __init__(self, key=None, http=None):
        self.key = key if key is not None else C.FINNHUB_API_KEY; self.http = http or http_json
    def configured(self): return bool(self.key)
    def calendar(self, date_from, date_to):
        url = f"{C.FINNHUB_BASE}/calendar/earnings?from={date_from}&to={date_to}&token={self.key}"
        st, j, _, err = self.http(url)
        if st != 200 or not isinstance(j, dict): return [], f"finnhub HTTP {st} {err or ''}".strip()
        rows = []
        for e in j.get("earningsCalendar", []):
            rows.append({"code": e.get("symbol"), "date": e.get("date"), "when": e.get("hour"), "eps_est": e.get("epsEstimate"),
                         "eps_act": e.get("epsActual"), "rev_est": e.get("revenueEstimate"), "rev_act": e.get("revenueActual")})
        return rows, None


_sources = {}
def get_source(kind, store=None):
    """kind: toss | dart | us_bars | fx | earnings. Toss is returned only when credentials exist."""
    if kind not in _sources:
        if kind == "toss":
            if not (C.TOSS_CLIENT_ID and C.TOSS_CLIENT_SECRET): _sources[kind] = None
            else:
                if store is None:
                    import marketdb   # shared token cache: one valid token per client, a new one revokes the old
                    store = marketdb.KVStore(marketdb.mdb())
                _sources[kind] = TossQuotes(store=store)
        elif kind == "dart": _sources[kind] = DartOpen() if C.DART_API_KEY else None
        elif kind == "us_bars": _sources[kind] = UsDailyBars()
        elif kind == "fx": _sources[kind] = FxPublic()
        elif kind == "earnings": _sources[kind] = FinnhubEarnings() if C.FINNHUB_API_KEY else None
        else: raise KeyError(kind)
    return _sources[kind]

def reset_sources(): _sources.clear()
