"""The Toss client is quotes-only: no order/account surface, path allowlist (templates), GET only, symbol validation,
token cache + 401 refresh, 429 retry, rate limiter, official response shapes (result envelope, string numbers), flag mapping."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done, DESK
import config as C
import quotes as Q
import marketdb as M
import common

# 1. no forbidden word anywhere in the client surface; no account header
surface = [n for n in dir(Q.TossQuotes) if not n.startswith("__")] + list(Q.TOSS_ENDPOINTS) + list(Q.ALLOWED_PATHS)
for w in Q.FORBIDDEN_WORDS:
    check(f"no '{w}' in surface", not any(w in s.lower() for s in surface), [s for s in surface if w in s.lower()])
src = open(os.path.join(DESK, "quotes.py"), encoding="utf-8").read()
for p in ("/api/v1/accounts", "/api/v1/holdings", "/api/v1/orders", "/api/v1/conditional-orders", "/api/v1/buying-power", "/api/v1/sellable-quantity", "/api/v1/commissions"):
    check(f"no {p} in quotes.py", p not in src)
check("no X-Tossinvest-Account header in quotes.py", "X-Tossinvest-Account\"" not in src and "'X-Tossinvest-Account'" not in src)
check("only GET endpoints besides the token", all(e["method"] == "GET" for k, e in Q.TOSS_ENDPOINTS.items() if k != "token"))

# 2. fake server with the official shapes
class FakeHTTP:
    def __init__(self): self.calls = []; self.token_calls = 0; self.next_status = []
    def __call__(self, url, method="GET", body=None, timeout=12, headers=None, form=None):
        self.calls.append((url, method, headers or {}, form))
        if url.endswith("/oauth2/token"):
            self.token_calls += 1
            return 200, {"access_token": f"tok{self.token_calls}", "token_type": "Bearer", "expires_in": 86400}, 5.0, None
        if self.next_status:
            st = self.next_status.pop(0); return st, {"error": {"code": "x", "message": "m", "requestId": "r"}}, 5.0, f"HTTP {st}"
        path = url.split("?")[0].replace(C.TOSS_BASE, "")
        if path == "/api/v1/prices":
            syms = url.split("symbols=")[1].split("&")[0].split(",")
            return 200, {"result": [{"symbol": s, "timestamp": "2026-10-29T15:00:00+09:00", "lastPrice": "72000", "currency": "KRW"} for s in syms]}, 5.0, None
        if path == "/api/v1/candles":
            return 200, {"result": {"candles": [
                {"timestamp": "2026-10-29T00:00:00+09:00", "openPrice": "71000", "highPrice": "72500", "lowPrice": "70500", "closePrice": "72000", "volume": "1000", "currency": "KRW"},
                {"timestamp": "2026-10-28T00:00:00+09:00", "openPrice": "70000", "highPrice": "71200", "lowPrice": "69800", "closePrice": "70000", "volume": "900", "currency": "KRW"}],
                "nextBefore": None}}, 5.0, None
        if path == "/api/v1/rankings":
            return 200, {"result": {"rankedAt": "2026-10-29T15:00:00+09:00", "rankings": [
                {"rank": 1, "symbol": "005930", "currency": "KRW", "price": {"lastPrice": "72000", "basePrice": "70000", "changeRate": "0.0286"},
                 "tradingVolume": "100", "tradingAmount": "7200000"}]}}, 5.0, None
        if path == "/api/v1/stocks":
            return 200, {"result": [{"symbol": "005930", "name": "삼성전자", "market": "KOSPI", "securityType": "STOCK", "status": "ACTIVE", "sharesOutstanding": "5919637922",
                                     "koreanMarketDetail": {"liquidationTrading": False, "krxTradingSuspended": True}},
                                    {"symbol": "069500", "name": "KODEX 200", "market": "KOSPI", "securityType": "ETF", "status": "DELISTED", "sharesOutstanding": "1",
                                     "koreanMarketDetail": {"liquidationTrading": True, "krxTradingSuspended": False}}]}, 5.0, None
        if path.endswith("/warnings"):
            return 200, {"result": [{"warningType": "INVESTMENT_WARNING", "startDate": "2026-10-20", "endDate": None},
                                    {"warningType": "OVERHEATED", "startDate": "2026-10-01", "endDate": "2026-10-10"},
                                    {"warningType": "VI_STATIC", "startDate": "2026-10-29", "endDate": None}]}, 5.0, None
        if path.endswith("/investor-trading"):
            return 200, {"result": {"nextUntil": None, "records": [
                {"date": "2026-10-29", "foreigner": {"netBuyVolume": "100"}, "institution": {"netBuyVolume": "-50"}, "individual": None},
                {"date": "2026-10-28", "foreigner": {"netBuyVolume": "10"}, "institution": {"netBuyVolume": "20"}, "individual": {"netBuyVolume": "-30"}}]}}, 5.0, None
        if path == "/api/v1/exchange-rate":
            return 200, {"result": {"baseCurrency": "USD", "quoteCurrency": "KRW", "rate": "1405.5", "midRate": "1400", "basisPoint": "40"}}, 5.0, None
        return 404, {"error": {"code": "not-found"}}, 5.0, "HTTP 404"

fh = FakeHTTP(); slept = []
tq = Q.TossQuotes(client_id="id", client_secret="sec", store={}, limiter=Q.RateLimiter({g: 1e6 for g in C.TOSS_RPS}), http=fh, sleep=slept.append)

q, err = tq.quote("KRX", "005930")
check("quote: price from /prices, OHLV from today's candle, change vs prev close", err is None and q["price"] == 72000 and q["open"] == 71000
      and q["high"] == 72500 and q["volume"] == 1000 and abs(q["change_pct"] - (72000 / 70000 - 1) * 100) < 1e-9 and q["turnover"] is None, q)
check("bearer token, no account header", fh.calls[-1][2].get("Authorization") == "Bearer tok1" and not any("Account" in k for k in fh.calls[-1][2]))
check("token issued once and cached", fh.token_calls == 1)
bars, err = tq.daily_bars("KRX", "005930", 5)
check("candles reversed to oldest first, strings -> floats", [b["date"] for b in bars] == ["2026-10-28", "2026-10-29"] and bars[-1]["c"] == 72000.0, bars)
rk, err = tq.ranking("KRX", "turnover", 5)
check("ranking: changeRate fraction -> percent, amount -> turnover", rk[0]["change_pct"] == 2.86 and rk[0]["turnover"] == 7200000.0 and rk[0]["code"] == "005930", rk)
check("ranking uses MARKET_TRADING_AMOUNT realtime KR", "type=MARKET_TRADING_AMOUNT" in fh.calls[-1][0] and "marketCountry=KR" in fh.calls[-1][0] and "duration=realtime" in fh.calls[-1][0])
tq.ranking("KRX", "change_pct", 5)
check("gainers ranking uses duration 1d (realtime not allowed)", "type=TOP_GAINERS" in fh.calls[-1][0] and "duration=1d" in fh.calls[-1][0])
fl, err = tq.stock_flags_many("KRX", ["005930", "069500"], day="2026-10-29")
check("flags: suspension + active warning only (VI ignored, expired skipped)", fl["005930"]["flags"] == sorted(["거래정지", "투자경고"]), fl["005930"])
check("flags: liquidation + delisted; ETF instrument", set(fl["069500"]["flags"]) >= {"정리매매", "상장폐지"} and fl["069500"]["instrument"] == "ETF", fl["069500"])
check("stocks: name/shares parsed", fl["005930"]["name"] == "삼성전자" and fl["005930"]["shares"] == 5919637922.0)
flow, err = tq.investor_flow("005930", 5)
check("investor flow oldest first, net volume floats, missing group None", [r["date"] for r in flow] == ["2026-10-28", "2026-10-29"]
      and flow[-1]["foreign_net_vol"] == 100.0 and flow[-1]["inst_net_vol"] == -50.0 and flow[-1]["retail_net_vol"] is None, flow)
fx, err = tq.fx_rate()
check("fx uses midRate", fx == 1400.0, fx)

# 3. symbol validation (path injection) and allowlist
for bad in ("../orders", "005930/../../accounts", "A B", "", "x" * 30):
    try: tq.warnings(bad); check(f"bad symbol {bad!r} refused", False)
    except AssertionError: check(f"bad symbol {bad!r} refused", True)
try: tq._get("prices", symbols="005930&x=../orders"); check("bad query value refused", False)
except AssertionError: check("bad query value refused", True)
Q.TOSS_ENDPOINTS["_bad"] = {"method": "GET", "path": "/api/v1/orders", "group": "MARKET_DATA"}
try: tq._get("_bad"); check("non-allowlisted path refused", False)
except AssertionError: check("non-allowlisted path refused", True)
finally: del Q.TOSS_ENDPOINTS["_bad"]
Q.TOSS_ENDPOINTS["_post"] = {"method": "POST", "path": "/api/v1/prices", "group": "MARKET_DATA"}
try: tq._get("_post"); check("non-GET refused", False)
except AssertionError: check("non-GET refused", True)
finally: del Q.TOSS_ENDPOINTS["_post"]

# 4. 401 -> one refresh; 429 -> one wait and retry; second failure -> error (no loop)
fh.next_status = [401]; n0 = fh.token_calls
q, err = tq.quote("KRX", "005930")
check("401 refreshes the token once then succeeds", err is None and fh.token_calls == n0 + 1)
fh.next_status = [429]; slept.clear()
r, err = tq._get("exchange_rate", baseCurrency="USD", quoteCurrency="KRW")
check("429 waits then retries once", err is None and slept and slept[-1] == C.TOSS_429_WAIT_S, (err, slept))
fh.next_status = [429, 429]
r, err = tq._get("exchange_rate", baseCurrency="USD", quoteCurrency="KRW")
check("second 429 returns an error (no loop)", err and "429" in err, err)

# 5. token store shared via market.db (one valid token per client)
kv = M.KVStore(M.mdb())
t1 = Q.TossQuotes(client_id="id", client_secret="sec", store=kv, limiter=Q.RateLimiter({g: 1e6 for g in C.TOSS_RPS}), http=fh)
t2 = Q.TossQuotes(client_id="id", client_secret="sec", store=kv, limiter=Q.RateLimiter({g: 1e6 for g in C.TOSS_RPS}), http=fh)
n0 = fh.token_calls; t1.quote("KRX", "005930"); t2.quote("KRX", "005930")
check("two clients share one token via market.db kv", fh.token_calls == n0 + 1)
kv["toss_token"] = {"access": "old", "expires_ts": time.time() + C.TOSS_TOKEN_MARGIN_S - 1}
t1.quote("KRX", "005930")
check("near-expiry token refreshed", fh.token_calls == n0 + 2)

# 6. limiter spacing, config limits = 80% of the published table
rl = Q.RateLimiter({"MARKET_DATA": 10.0}); sl = []
for _ in range(3): rl.wait("MARKET_DATA", sleep=sl.append)
check("limiter schedules calls 0.1s apart", len(sl) == 2 and 0.09 <= sl[0] <= 0.11 and 0.19 <= sl[1] <= 0.21, sl)
published = {"AUTH": 5, "STOCK": 5, "STOCK_TRADING_TREND": 10, "MARKET_INFO": 3, "MARKET_DATA": 15, "MARKET_DATA_CHART": 20, "RANKING": 5}
check("TOSS_RPS = 80% of published", all(abs(C.TOSS_RPS[g] - 0.8 * v) < 1e-9 for g, v in published.items()), C.TOSS_RPS)
check("every endpoint group has a limit", all(e["group"] in C.TOSS_RPS for e in Q.TOSS_ENDPOINTS.values()))

# 7. hosted World Monitor still refused; no creds -> no Toss source
try: common.http_json("https://api.worldmonitor.app/x"); check("api.worldmonitor.app refused", False)
except AssertionError: check("api.worldmonitor.app refused", True)
Q.reset_sources()
check("no creds -> no Toss source", Q.get_source("toss") is None and Q.get_source("fx") is not None)
done()
