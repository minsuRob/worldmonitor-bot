"""Offline tests for book D's two entry filters (2026-10-29): quote token SOL/USDC/USDT only, and no chasing (>= 2.5x within 30 min).
Throw-away COPY of the desk code (fresh state dir), no network (GeckoTerminal/Helius are faked), no real ledgers.
Also replays token "0" (0/ZEC pool) with the real saved 1-minute candles in analysis/d_cadence_0 at its 11:18 KST entry.
  python3 manual/tests/test_d_entry_filters.py"""
import sys, os, shutil, tempfile, json, time, datetime
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="d_entry_")
for f in os.listdir(SRC):
    if f.endswith(".py"): shutil.copy(os.path.join(SRC, f), TMP)
shutil.copytree(os.path.join(SRC, "manual"), os.path.join(TMP, "manual"), ignore=shutil.ignore_patterns("variant_cycles", "*.json", "__pycache__", "tests"))
sys.path.insert(0, TMP); sys.path.insert(0, os.path.join(TMP, "manual"))
os.environ.pop("HELIUS_API_KEY", None)
import config as C
assert C.STATE.startswith(TMP)
C.HELIUS_RPC = None
import bots, common
def f_rpc(mint, lg): return (1e9, [("acct", 0.01 * 1e9, "owner")], set(), "fake-rpc")
bots.top_holders_rpc, bots.pair_by_address = f_rpc, lambda pair: ({"liquidity": {"usd": 1e9}, "priceUsd": "1"}, None)
bots.holder_count_helius = lambda mint, lg: (500, False, 1, "fake-das")
bots.top_holders_rugcheck = lambda m, lg: None
HTTP = []   # every http_json call made through bots (must stay empty except the faked GeckoTerminal ones)
def fake_http(url, method="GET", body=None, *a, **k):
    HTTP.append(url); return FAKE_GT.pop(0) if FAKE_GT else (None, None, 1.0, "no fake response")
FAKE_GT = []
bots.http_json = fake_http
import run_variants as RV, book_rules as BR
lg = common.logger("test_d_entry")
OK = []
def check(name, cond, info=""):
    assert cond, f"FAIL {name} {info}"; OK.append(name)

SOL, USDC, USDT = "So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF8H8B7dGHuJsT5bbGsHq1JsjDAQr"
ZEC = "A7bdiYdS5GjqGFtxf17ppRHtDKPkkRqbKtR27dxvQXaS"
T = 1_800_000_000.0
def pair(quote=SOL, qsym="SOL", age_min=60):
    return {"quoteToken": {"address": quote, "symbol": qsym} if quote else None,
            "priceChange": {"m5": 2, "h1": 20, "h6": 30}, "txns": {"m5": {"buys": 40, "sells": 20}, "h1": {"buys": 100, "sells": 80}},
            "volume": {"m5": 1500, "h1": 6000, "h24": 50_000, "h6": 20_000}, "liquidity": {"usd": 50_000}, "pairCreatedAt": (T - age_min * 60) * 1000}
def pc(p): return p["pairCreatedAt"] / 1000
def candles(prices, t_end=T):
    """prices oldest -> newest, one per minute, last candle starts at t_end - 60. high = low = price*(1 +- 1%)."""
    n = len(prices)
    return [[int(t_end - 60 * (n - i)), px, px * 1.01, px * 0.99, px, 100.0] for i, px in enumerate(prices)]

# ---------- 1. quote-token filter (D only)
check("D SOL quote passes", BR.precheck("D", pair(SOL), pc(pair()), T) is None)
check("D USDC quote passes", BR.precheck("D", pair(USDC, "USDC"), pc(pair()), T) is None)
check("D USDT quote passes", BR.precheck("D", pair(USDT, "USDT"), pc(pair()), T) is None)
r = BR.precheck("D", pair(ZEC, "ZEC"), pc(pair()), T)
check("D ZEC quote rejected", r and r[0] == "D_quote_not_sol" and "ZEC" in r[1], r)
r = BR.precheck("D", pair(None), pc(pair()), T); check("D unknown quote rejected", r and r[0] == "D_quote_not_sol" and "unknown" in r[1], r)
for v in ("BASE", "A", "B"):
    check(f"{v} ignores quote token", BR.precheck(v, pair(ZEC, "ZEC"), pc(pair()), T) is None)
pC = pair(ZEC, "ZEC"); pC["priceChange"]["h1"] = 40
check("C ignores quote token", BR.precheck("C", pC, pc(pC), T) is None)

# ---------- 2. run30 math
flat = candles([1.0] * 60)
r = BR.run_multiple(flat, T); check("flat run ~1.02x", r and abs(r["multiple"] - 1.01 / 0.99) < 1e-3, r)
run28 = candles([1.0] * 32 + [1.0 + 1.8 * i / 20 for i in range(1, 21)] + [2.8] * 8)    # 1.0 -> 2.8 in 20 min, top 10 min ago
r = BR.run_multiple(run28, T); check("2.8x run measured >= 2.5", r["multiple"] >= 2.5 and r["multiple"] < 3.0, r)
run15 = candles([1.0] * 32 + [1.0 + 0.5 * i / 20 for i in range(1, 21)] + [1.5] * 8)
r = BR.run_multiple(run15, T); check("1.5x run measured < 2.5", 1.45 < r["multiple"] < 1.6, r)
old = candles([1.0] * 10 + [3.0] * 50)   # ran 3x 50 minutes ago, flat since: not a run within the last 30 min
r = BR.run_multiple(old, T); check("old 3x run (> 30m ago, flat since) not counted", r["multiple"] < 1.1, r)
dump = candles([1.0] * 30 + [3.0] * 15 + [1.0] * 15)   # window starts at 3.0   # top then dump inside the window: low AFTER the high does not count
r = BR.run_multiple(dump, T); check("dump after top not counted as run", r["multiple"] < 1.1, r)
edge = candles([1.0] * 31 + [2.6] * 29)   # low at T-30m exactly is outside (start must be > T-30m), so no run
r = BR.run_multiple(edge, T); check("window edge: candle starting at t-30m excluded", r["multiple"] < 1.1, r)
edge2 = candles([1.0] * 32 + [2.6] * 28)  # last 1.0 candle starts T-29m: inside -> 2.6x
r = BR.run_multiple(edge2, T); check("2.6x inside window rejected-size", r["multiple"] >= 2.5, r)
check("no candle in last 30m -> None", BR.run_multiple(candles([1.0] * 20, T - 40 * 60), T) is None)
check("empty candles -> None", BR.run_multiple([], T) is None)
check("unsorted input same result", BR.run_multiple(list(reversed(run28)), T)["multiple"] == BR.run_multiple(run28, T)["multiple"])
check("thresholds are named constants", BR.D_RUN30_MAX_MULT == 2.5 and BR.D_RUN30_WINDOW_MIN == 30
      and BR.PARAMS["D"]["run30"] == {"window_min": 30, "max_mult": 2.5} and set(BR.D_QUOTE_ALLOW) == {SOL, USDC, USDT})

# ---------- 3. run30_check (fetch injected)
fx = lambda data, note="fake": (lambda pool, lg=None, t=None: (data, note))
rej, info = BR.run30_check("D", "poolX", T, lg, fx(run28))
check("D 2.8x run rejected", rej and rej[0] == "D_run30_ge_2.5x" and "x within 30m" in rej[1] and info["result"] == "reject", (rej, info))
check("reject detail has multiple", f"{info['multiple']:.2f}x" in rej[1])
rej, info = BR.run30_check("D", "poolX", T, lg, fx(run15)); check("D 1.5x run passes", rej is None and info["result"] == "pass", (rej, info))
rej, info = BR.run30_check("D", "poolX", T, lg, fx(None, "HTTP 429; HTTP 429; HTTP 429"))
check("fetch failure -> D_run30_unknown", rej and rej[0] == "D_run30_unknown" and "429" in rej[1] and info["result"] == "unknown", (rej, info))
def boom(pool, lg=None, t=None): raise RuntimeError("socket died")
rej, info = BR.run30_check("D", "poolX", T, lg, boom); check("fetch exception -> D_run30_unknown", rej[0] == "D_run30_unknown")
rej, info = BR.run30_check("D", "poolX", T, lg, fx(candles([1.0] * 20, T - 40 * 60))); check("stale candles -> D_run30_unknown", rej[0] == "D_run30_unknown")
for v in ("BASE", "A", "B", "C"):
    check(f"{v} has no run30 check", BR.run30_check(v, "poolX", T, lg, boom) == (None, None) and "run30" not in BR.PARAMS[v])

# ---------- 4. fetch_ohlcv_1m: throttle + retry on 429, fail closed after retries, 404 not retried (sleeps faked)
SLEEPS = []; real_sleep = BR.time.sleep; real_thr = bots._throttle
BR.time.sleep = lambda s: SLEEPS.append(s); bots._throttle = lambda b, rps: None   # throttle checked separately below
gt_ok = (200, {"data": {"attributes": {"ohlcv_list": run15}}}, 5.0, None)
HTTP.clear(); FAKE_GT[:] = [(429, None, 5.0, "HTTP 429"), gt_ok]
data, note = BR.fetch_ohlcv_1m("poolA", lg, t=T)
check("429 then 200 -> candles", data == run15 and "attempt 2" in note and len(HTTP) == 2 and SLEEPS == [BR.GT_RETRY_SLEEPS[0]], (note, HTTP, SLEEPS))
check("GeckoTerminal URL", HTTP[0].startswith("https://api.geckoterminal.com/api/v2/networks/solana/pools/poolA/ohlcv/minute?aggregate=1&limit=40&currency=usd"), HTTP[0])
HTTP.clear(); data, note = BR.fetch_ohlcv_1m("poolA", lg, t=T); check("same pool same minute cached", data == run15 and HTTP == [])
HTTP.clear(); SLEEPS.clear(); FAKE_GT[:] = [(429, None, 5.0, "HTTP 429")] * 3
data, note = BR.fetch_ohlcv_1m("poolB", lg, t=T); check("3x 429 -> None", data is None and len(HTTP) == 3 and len(SLEEPS) == 2, (note, HTTP))
HTTP.clear(); FAKE_GT[:] = [(404, None, 5.0, "HTTP 404")]
data, note = BR.fetch_ohlcv_1m("poolC", lg, t=T); check("404 not retried", data is None and len(HTTP) == 1)
HTTP.clear(); FAKE_GT[:] = [(None, None, 5.0, "URLError: timeout"), (None, None, 5.0, "URLError: timeout"), gt_ok]
data, note = BR.fetch_ohlcv_1m("poolD", lg, t=T); check("network errors retried", data == run15 and len(HTTP) == 3)
BR.time.sleep = real_sleep
th = []
bots._throttle = lambda b, rps: th.append((b, rps))
FAKE_GT[:] = [gt_ok]; BR.fetch_ohlcv_1m("poolE", lg, t=T); bots._throttle = real_thr
check("throttled ~27/min", th == [("geckoterminal", BR.GT_RPS)] and BR.GT_RPS * 60 <= 30)

# ---------- 5. full prepare(): D rejects ZEC + chaser, records run30 in the cycle record; other books unaffected; no network
mk = lambda tag: (tag + "1" * 40)[:44]
def full_pair(tok, quote=SOL, qsym="SOL"):
    p = pair(quote, qsym); p.update({"baseToken": {"address": tok, "symbol": tok[:5]}, "pairAddress": "pool_" + tok[:8], "dexId": "raydium",
                                     "priceUsd": "1.0", "fdv": 1e6, "marketCap": 1e6, "pairCreatedAt": (time.time() - 3600) * 1000})
    p["priceChange"]["h1"] = 20
    return p
toks = {mk("ZECQ"): (ZEC, "ZEC"), mk("CHASE"): (SOL, "SOL"), mk("CALM"): (USDC, "USDC"), mk("NODATA"): (SOL, "SOL")}
pairs = {t: full_pair(t, q, s) for t, (q, s) in toks.items()}
now_ = time.time()
GT = {"pool_" + mk("CHASE")[:8]: candles([1.0] * 32 + [1.0 + 1.8 * i / 20 for i in range(1, 21)] + [2.8] * 8, now_),
      "pool_" + mk("CALM")[:8]: candles([1.0] * 32 + [1.0 + 0.5 * i / 20 for i in range(1, 21)] + [1.5] * 8, now_)}
GT_CALLS = []
def fake_fetch(pool, lg=None, limit=40, t=None):
    GT_CALLS.append(pool); return (GT[pool], "fake 200") if pool in GT else (None, "HTTP 429; HTTP 429; HTTP 429")
BR.fetch_ohlcv_1m = fake_fetch
bots.scan_fetch = lambda lg: {"tokens": list(toks), "errs": [], "pairs": pairs, "perrs": []}
RV.STORE = os.path.join(TMP, "store"); HTTP.clear()
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()): RV.prepare()
cyc = json.load(open(sorted(f for f in __import__("glob").glob(os.path.join(TMP, "manual", "variant_cycles", "meme-var-*.json")) if "result" not in f)[-1]))
D = {r["symbol"]: r for r in cyc["variants"]["D"]}
check("prepare D: ZEC quote rejected", D["ZECQ1"]["vet_check"] == "D_quote_not_sol", D["ZECQ1"])
check("prepare D: chaser rejected with multiple", D["CHASE"]["vet_check"] == "D_run30_ge_2.5x" and D["CHASE"]["run30"]["multiple"] >= 2.5, D["CHASE"])
check("prepare D: calm 1.5x passes", D["CALM1"]["vet_result"] != "REJECT" and D["CALM1"]["run30"]["result"] == "pass", D["CALM1"])
check("prepare D: no candles -> D_run30_unknown", D["NODAT"]["vet_check"] == "D_run30_unknown", D["NODAT"])
check("GeckoTerminal only for D candidates that passed everything else (3 pools, not ZEC)",
      sorted(GT_CALLS) == sorted({"pool_" + mk(x)[:8] for x in ("CHASE", "CALM", "NODATA")}) and len(GT_CALLS) == 3, GT_CALLS)
check("no real network call in prepare", HTTP == [], HTTP)
for v in ("BASE", "A", "B"):
    rs = cyc["variants"][v]
    check(f"prepare {v} unaffected (no D_ checks, no run30)", all(not (r["vet_check"] or "").startswith("D_") and "run30" not in r for r in rs)
          and any(r["symbol"] in ("ZECQ1", "CHASE") and r["vet_result"] != "REJECT" for r in rs), [(r["symbol"], r["vet_check"]) for r in rs])
check("prepare C unaffected (no D_ checks)", all(not (r["vet_check"] or "").startswith("D_") and "run30" not in r for r in cyc["variants"]["C"]))
check("D jobs only for CALM", [j["symbol"] for j in cyc["jobs"] if j["book"] == "D"] == ["CALM1"], cyc["jobs"])
check("D rules text mentions filters", "SOL/USDC/USDT only" in cyc["books"]["D"]["rules"] and ">= 2.5x run within 30 minutes" in cyc["books"]["D"]["rules"])

# ---------- 6. replay token "0" (0/ZEC) with the real saved candles at the 11:18 KST entry
AN = os.path.join(SRC, "analysis", "d_cadence_0")
c0 = json.load(open(os.path.join(AN, "ohlcv_1m.json")))["data"]["attributes"]["ohlcv_list"]
p0 = json.load(open(os.path.join(AN, "dexscreener_pair_0.json"))); p0 = p0.get("pair") or p0["pairs"][0]
KST = datetime.timezone(datetime.timedelta(hours=9))
hm = lambda ts: datetime.datetime.fromtimestamp(ts, KST).strftime("%H:%M")
for hhmm in ("11:18", "11:20"):
    t_e = datetime.datetime(2026, 10, 29, int(hhmm[:2]), int(hhmm[3:]), tzinfo=KST).timestamp()
    rej, info = BR.run30_check("D", p0["pairAddress"], t_e, lg, fx(c0))
    print(f"replay '0' at {hhmm} KST: run30 {info['multiple']:.2f}x (low {info['low']:.4g} @ {hm(info['low_ts'])} -> high {info['high']:.4g} @ {hm(info['high_ts'])}) -> {rej}")
    check(f"replay '0' {hhmm} run30 rejects", rej and rej[0] == "D_run30_ge_2.5x")
q = BR.precheck("D", p0, None, T); print(f"replay '0' quote check: {q}")
check("replay '0' quote rejects (ZEC)", q and q[0] == "D_quote_not_sol" and "ZEC" in q[1])
print(f"ALL {len(OK)} CHECKS OK  (tmp copy {TMP})")
