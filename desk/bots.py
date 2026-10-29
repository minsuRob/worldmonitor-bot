"""Six paper-trading bots. Usage: python3 bots.py <scan|vet|book|size|fills|risk>
PAPER ONLY: no wallets, no signing keys, no order submission anywhere. Read-only RPC only
(Helius read-only API key from env HELIUS_API_KEY, never logged)."""
import sys, json, time, traceback, sqlite3, threading
import config as C
from common import *

# ------------------------------------------------------------------ helpers
def equity_now(c):
    rows, mv, _ = mark_positions(c)
    return cash(c) + mv

def planned_meme_order(c, liq):
    """What SIZE would allocate (used by VET check 2/6 and by SIZE). Returns (dollars, kelly_raw, kelly_capped, reason)."""
    p, b = C.MEME_ASSUMED_P_WIN, C.MEME_ASSUMED_PAYOFF_B
    k_raw = p - (1 - p) / b
    k_cap = max(0.0, min(k_raw, C.KELLY_CAP))
    fixed = getattr(C, "SIZE_FIXED_FRACTION", None)   # variant books C/D only (manual/book_rules.py); unset for the desk/BASE
    if fixed: k_cap = fixed
    eq = equity_now(c)
    free = cash(c) - encumbered(c)
    d = k_cap * eq
    reason = []
    if d > free: d = free; reason.append("limited by unencumbered cash")
    liq_cap = liq / C.VET_LIQ_MULT
    if d > liq_cap: d = liq_cap; reason.append("limited by liquidity/50")
    slip_cap = C.SLIPPAGE_BUDGET * (liq / 2.0) / 2.0   # round-trip modeled impact within 2% budget
    if d > slip_cap: d = slip_cap; reason.append("limited by 2% round-trip slippage budget")
    return max(d, 0.0), k_raw, k_cap, "; ".join(reason)

# ------------------------------------------------------------------ SCAN
def scan_once(c, lg):
    """Legacy single-book SCAN = shared fetch + this ledger's filter (behaviour unchanged)."""
    return scan_filter(c, lg, scan_fetch(lg))

def scan_fetch(lg):
    """Raw DexScreener data only (no ledger access): shared by every paper book in a variant cycle."""
    srcs = ["/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1"]
    tokens, errs = [], []
    for s in srcs:
        st, j, lat, err = http_json(C.DEX + s)
        if st == 200 and isinstance(j, list):
            for x in j:
                if x.get("chainId") == "solana" and x.get("tokenAddress") not in tokens:
                    tokens.append(x["tokenAddress"])
        else: errs.append(f"{s}: {err}")
    pairs, perrs = best_pairs(tokens) if tokens else ({}, [])
    return {"tokens": tokens, "errs": errs, "pairs": pairs, "perrs": perrs}

def scan_filter(c, lg, f):
    """Per-ledger SCAN filter: this book's own 60-min seen-recently and already-held sets, drops and candidates."""
    tokens, errs, pairs, perrs = f["tokens"], f["errs"], f["pairs"], f["perrs"]
    kv_set(c, "scan_last", {"ts": now(), "tokens": len(tokens), "errors": errs})
    if not tokens:
        event(c, "scan", "SCAN_NO_DATA", {"errors": errs}); return
    since = now() - C.SCAN_DEDUP_MIN * 60
    recent = {r["token"] for r in c.execute("SELECT token FROM candidates WHERE ts>?", (since,))}
    held = {r["token"] for r in c.execute("SELECT token FROM positions WHERE status='OPEN'")}
    keep = []
    for t in tokens:
        p = pairs.get(t)
        if not p: continue
        sym = (p.get("baseToken") or {}).get("symbol")
        liq = (p.get("liquidity") or {}).get("usd") or 0
        tx = p.get("txns") or {}
        m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
        vol = p.get("volume") or {}
        def drop(reason):
            c.execute("INSERT INTO scan_drops (ts,token,symbol,pair,reason,data) VALUES (?,?,?,?,?,?)",
                      (now(), t, sym, p.get("pairAddress"), reason, json.dumps({"liq": liq, "m5": m5, "h1": h1})))
        if t in held or t in recent: continue
        if liq < C.SCAN_MIN_LIQ: drop(f"liquidity.usd {liq:.0f} < {C.SCAN_MIN_LIQ:.0f}"); continue
        if (m5.get("sells", 0) > m5.get("buys", 0)) and (h1.get("sells", 0) > h1.get("buys", 0)):
            drop("sells > buys in last two windows (m5, h1)"); continue
        vh1 = vol.get("h1") or 0; vm5 = vol.get("m5") or 0
        bh1 = h1.get("buys") or 0; bm5 = m5.get("buys") or 0
        # rate of change, not absolute size: 5-min pace vs hourly pace
        score = 0.5 * (vm5 * 12 / vh1 if vh1 else 0) + 0.5 * (bm5 * 12 / bh1 if bh1 else 0)
        warnings = ["holders unknown: cannot compare holder growth vs price"]
        keep.append((score, t, sym, p, liq, warnings))
    keep.sort(key=lambda x: -x[0])
    for score, t, sym, p, liq, warnings in keep[:C.SCAN_MAX]:
        c.execute("""INSERT INTO candidates (ts,token,symbol,pair,dex,liquidity,fdv,mcap,price,pair_created,score,holders,holders_source,
                     warnings,data,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (now(), t, sym, p.get("pairAddress"), p.get("dexId"), liq, p.get("fdv"), p.get("marketCap"),
                   float(p.get("priceUsd") or 0), (p.get("pairCreatedAt") or 0) / 1000, score, None,
                   "unknown (DexScreener does not provide holder counts)", json.dumps(warnings), json.dumps(p), "NEW"))
    lg.info(f"scan: tokens={len(tokens)} pairs={len(pairs)} kept={min(len(keep), C.SCAN_MAX)} errors={errs + perrs}")

# ------------------------------------------------------------------ VET
_THROTTLE = {}
_THROTTLE_LOCK = threading.Lock()
def _throttle(bucket, rps):
    """Simple min-interval throttle per bucket (Helius free plan: 10 rps RPC, 2 rps DAS)."""
    with _THROTTLE_LOCK:
        nxt = _THROTTLE.get(bucket, 0.0); t = time.monotonic()
        if nxt > t: time.sleep(nxt - t); t = nxt
        _THROTTLE[bucket] = t + 1.0 / rps

def _ep_label(ep):
    """Endpoint name for logs/sources. Never includes the query string (keys live there)."""
    if C.HELIUS_RPC and ep == C.HELIUS_RPC: return "helius"
    return ep.split("?")[0].replace("https://", "")

def _redact(x):
    x = str(x)
    return x.replace(C.HELIUS_API_KEY, "***") if C.HELIUS_API_KEY else x

RPC_LAST_SRC = {}
def rpc(method, params, lg):
    """Read-only JSON-RPC across C.SOLANA_RPCS with retry/backoff. 429/403/401 or a JSON error
    moves straight to the next endpoint (those are method blocks, not transient).
    RPC_LAST_SRC[method] = label of the endpoint that answered."""
    errs = []
    for ep in C.SOLANA_RPCS:
        helius = bool(C.HELIUS_RPC) and ep == C.HELIUS_RPC
        for i in range(C.RPC_RETRIES):
            if helius: _throttle("helius", C.HELIUS_RPS)
            st, j, lat, err = http_json(ep, "POST", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if st == 200 and j and j.get("result") is not None:
                RPC_LAST_SRC[method] = _ep_label(ep); return j["result"]
            code = ((j or {}).get("error") or {}).get("code") if isinstance(j, dict) else None
            errs.append(f"{_ep_label(ep)}:{_redact(st or err)}:{code}")
            if st in (401, 403, 404) or code in (-32602, -32603, -32052, 35): break
            if st == 429 or code == 429:
                if helius and i == 0: time.sleep(1.0); continue   # own key: one short wait, then fall back
                break
            time.sleep(C.RPC_BACKOFF_S * 2 ** i)
    lg.info(f"rpc {method} no answer: {errs[-6:]}")
    return None

def holder_count_helius(mint, lg):
    """Helius DAS getTokenAccounts(mint): non-zero token accounts, paged 1000/page, 10 credits/page,
    capped at HOLDER_COUNT_MAX_PAGES. Returns (count, capped, pages, source) or None."""
    if not C.HELIUS_RPC: return None
    day = kst().strftime("%Y-%m-%d")
    with _snapdb() as s:
        used = (s.execute("SELECT credits FROM das_credits WHERE day=?", (day,)).fetchone() or [0])[0]
    if used + 10 * C.HOLDER_COUNT_MAX_PAGES > C.HELIUS_DAS_DAILY_CREDITS:
        lg.info(f"helius das daily credit budget reached ({used}/{C.HELIUS_DAS_DAILY_CREDITS}); holder count skipped")
        return None
    n, page = 0, 1
    while page <= C.HOLDER_COUNT_MAX_PAGES:
        res = None
        with _snapdb() as s:   # 10 credits per DAS request, counted before sending
            s.execute("INSERT INTO das_credits (day, credits) VALUES (?, 10) ON CONFLICT(day) DO UPDATE SET credits=credits+10", (day,))
        for i in range(2):
            if i:
                with _snapdb() as s:
                    s.execute("UPDATE das_credits SET credits=credits+10 WHERE day=?", (day,))
            _throttle("helius-das", C.HELIUS_DAS_RPS)
            st, j, lat, err = http_json(C.HELIUS_RPC, "POST", {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccounts",
                                        "params": {"mint": mint, "page": page, "limit": C.HOLDER_COUNT_PAGE}}, timeout=20)
            if st == 200 and isinstance(j, dict) and isinstance(j.get("result"), dict): res = j["result"]; break
            lg.info(f"helius das getTokenAccounts {mint} page {page} try {i+1}: {_redact(st or err)}")
            time.sleep(1.0 * (i + 1))
        if res is None: return None
        k = len(res.get("token_accounts") or [])
        n += k
        if k < C.HOLDER_COUNT_PAGE: return n, False, page, "helius-das"
        page += 1
    return n, True, page - 1, "helius-das"

def _snapdb():
    s = sqlite3.connect(C.HOLDER_SNAPSHOTS, timeout=30)
    s.execute("CREATE TABLE IF NOT EXISTS snaps (id INTEGER PRIMARY KEY, token TEXT, ts REAL, holders INTEGER, capped INTEGER, price REAL, src TEXT)")
    s.execute("CREATE INDEX IF NOT EXISTS snaps_tok ON snaps(token, ts)")
    s.execute("CREATE TABLE IF NOT EXISTS das_credits (day TEXT PRIMARY KEY, credits INTEGER)")
    return s

def check_price_vs_holders(cand, lg):
    """VET check 3. Returns (verdict, detail, holders, src): verdict 'REJECT' | 'OK' | 'PARTIAL'.
    Needs a Helius DAS holder count now and an earlier snapshot (>=30 min, <=24h) of the same token."""
    hc = holder_count_helius(cand["token"], lg)
    if not hc: return "PARTIAL", "3_price_vs_holders: not evaluable (holder count unavailable)", None, None
    n, capped, pages, src = hc
    tag = f"{'>=' if capped else ''}{n}"
    price = cand["price"] or 0.0
    t = now()
    with _snapdb() as s:
        prev = s.execute("SELECT ts, holders, capped, price FROM snaps WHERE token=? AND ts<=? AND ts>=? ORDER BY ts DESC LIMIT 1",
                         (cand["token"], t - C.VET_HOLDER_SNAPSHOT_MIN_AGE_MIN * 60, t - C.VET_HOLDER_SNAPSHOT_MAX_AGE_H * 3600)).fetchone()
        if not s.execute("SELECT 1 FROM snaps WHERE token=? AND ts>?", (cand["token"], t - 300)).fetchone():
            s.execute("INSERT INTO snaps (token, ts, holders, capped, price, src) VALUES (?,?,?,?,?,?)", (cand["token"], t, n, int(capped), price, src))
    if not prev:
        return "PARTIAL", f"3_price_vs_holders: holders {tag} ({src}), no earlier snapshot to compare", n, src
    pts, ph, pcap, pprice = prev
    if capped or pcap or not ph or not pprice:
        return "PARTIAL", f"3_price_vs_holders: holders {tag} vs {ph}{' (capped)' if pcap else ''}, cannot compare", n, src
    dp = (price / pprice - 1) * 100; dh = (n / ph - 1) * 100
    det = f"price {dp:+.1f}% vs holders {dh:+.1f}% ({ph}->{n}, {src}) over {(t - pts) / 60:.0f}m"
    if dp >= C.VET_PRICE_UP_PCT and dh < C.VET_HOLDERS_FLAT_PCT: return "REJECT", det, n, src
    return "OK", det, n, src

_RPC_HOLDERS_BLOCKED_UNTIL = 0.0

def top_holders_rpc(mint, lg):
    """Returns (total_supply_raw, [(token_account, amount_raw, owner)], source) or None."""
    global _RPC_HOLDERS_BLOCKED_UNTIL
    if time.time() < _RPC_HOLDERS_BLOCKED_UNTIL: return None   # every endpoint blocked it recently
    big = rpc("getTokenLargestAccounts", [mint], lg)
    if not big:
        _RPC_HOLDERS_BLOCKED_UNTIL = time.time() + C.RPC_BLOCK_COOLDOWN_S; return None
    sup = rpc("getTokenSupply", [mint], lg)
    if not sup: return None
    accts = big["value"][:5]
    infos = rpc("getMultipleAccounts", [[a["address"] for a in accts], {"encoding": "jsonParsed"}], lg)
    if not infos: return None
    rows = []
    for a, inf in zip(accts, infos["value"]):
        owner = (((inf or {}).get("data") or {}).get("parsed") or {}).get("info", {}).get("owner")
        rows.append((a["address"], float(a["amount"]), owner))
    return float(sup["value"]["amount"]), rows, set(), RPC_LAST_SRC.get("getTokenLargestAccounts", "solana-rpc")

def top_holders_rugcheck(mint, lg):
    """Public no-key RugCheck report: topHolders (with owner) + token supply + market (pool) accounts."""
    for i in range(C.RUGCHECK_RETRIES):
        st, j, lat, err = http_json(f"{C.RUGCHECK}/tokens/{mint}/report", timeout=20)
        if st == 200 and isinstance(j, dict) and j.get("topHolders") is not None and (j.get("token") or {}).get("supply"):
            pools = set()
            for m in j.get("markets") or []:
                for k in ("pubkey", "liquidityA", "liquidityB"):
                    if m.get(k): pools.add(m[k])
                for k in ("liquidityAAccount", "liquidityBAccount"):
                    acc = m.get(k) or {}
                    if isinstance(acc, dict) and acc.get("owner"): pools.add(acc["owner"])
            rows = [(h.get("address"), float(h.get("amount") or 0), h.get("owner")) for h in j["topHolders"][:5]]
            return float(j["token"]["supply"]), rows, pools, "rugcheck"
        lg.info(f"rugcheck {mint} try {i+1}: {st} {err}")
        time.sleep(C.RPC_BACKOFF_S * 2 ** (i + 1))
    return None

def check_top_holder(cand, lg):
    """VET check 1. Returns (ok: bool|None, detail). None = no data source answered."""
    res = top_holders_rpc(cand["token"], lg) or top_holders_rugcheck(cand["token"], lg)
    if not res: return None, "Solana RPC and RugCheck did not answer"
    total, rows, pools, src = res
    pools = set(pools) | {cand["pair"]}
    top, excluded = 0.0, []
    for addr, amt, owner in rows:
        if (owner and owner in pools) or addr in pools:
            excluded.append(addr); continue   # a DEX pool's own vault, not a wallet
        top = max(top, amt / total if total else 1.0)
    det = f"largest holder {top*100:.2f}% (src {src}, pool vaults excluded: {len(excluded)})"
    return top <= C.VET_TOP_HOLDER_MAX, det

def vet_one(c, cand, lg):
    """7 checks in order; stop at first REJECT. Returns (result, check, detail)."""
    partial = []
    p = json.loads(cand["data"])
    # 1 top holder
    ok, det = check_top_holder(cand, lg)
    if ok is None: return "REJECT", "1_top_holder", det
    if not ok: return "REJECT", "1_top_holder", det.replace("largest holder", "largest holder >5%:", 1)
    # 2 liquidity vs order
    liq = cand["liquidity"]
    order, *_ = planned_meme_order(c, liq)
    if liq < C.VET_MIN_LIQ or (order > 0 and liq < C.VET_LIQ_MULT * order):
        return "REJECT", "2_liquidity", f"liquidity {liq:.0f} vs order {order:.2f}"
    # 3 price up while holders flat (Helius DAS holder count vs this token's earlier snapshot)
    v3, d3, nh, hsrc = check_price_vs_holders(cand, lg)
    if nh is not None and "id" in cand.keys():
        c.execute("UPDATE candidates SET holders=?, holders_source=? WHERE id=?", (nh, hsrc, cand["id"]))
    if v3 == "REJECT": return "REJECT", "3_price_vs_holders", d3
    if v3 == "PARTIAL": partial.append(d3)
    # 4 already priced into h1
    h1 = ((p.get("priceChange") or {}).get("h1")) or 0
    if h1 >= C.VET_H1_ALREADY_PRICED:
        return "REJECT", "4_already_in_h1", f"priceChange.h1 {h1}% >= {C.VET_H1_ALREADY_PRICED}%"
    # 5 news single-source: SCAN candidates are not news-based
    # 6 edge after round-trip fees (edge uses ASSUMED p/b from config)
    if order <= 0: return "REJECT", "6_no_edge_after_fees", "planned order is 0"
    edge = C.MEME_ASSUMED_P_WIN * C.MEME_ASSUMED_PAYOFF_B - (1 - C.MEME_ASSUMED_P_WIN)
    costs = 2 * fee_for(order) / order + 2 * order / (liq / 2)
    if edge - costs <= 0:
        return "REJECT", "6_no_edge_after_fees", f"assumed edge {edge:.3f} - costs {costs:.3f} <= 0"
    # 7 young pair with shrinking liquidity (re-measure now)
    age_min = (now() - cand["pair_created"]) / 60 if cand["pair_created"] else None
    if age_min is not None and age_min < C.VET_MIN_AGE_MIN:
        fresh, err = pair_by_address(cand["pair"])
        if not fresh: return "REJECT", "7_young_shrinking_liq", f"age {age_min:.0f}m and liquidity unmeasurable: {err}"
        nl = (fresh.get("liquidity") or {}).get("usd") or 0
        if nl < liq: return "REJECT", "7_young_shrinking_liq", f"age {age_min:.0f}m, liquidity {liq:.0f} -> {nl:.0f}"
    if partial: return "PASS_PARTIAL", None, "; ".join(partial)
    return "PASS", None, ""

def vet_tick(c, lg, hb):
    for cand in c.execute("SELECT * FROM candidates WHERE status='NEW' ORDER BY score DESC").fetchall():
        hb()
        try: res, chk, det = vet_one(c, cand, lg)
        except Exception as e: res, chk, det = "REJECT", "error", f"{type(e).__name__}: {e}"
        c.execute("UPDATE candidates SET status=?, vet_result=?, vet_check=?, vet_detail=?, vet_ts=? WHERE id=?",
                  ("VETTED" if res != "REJECT" else "REJECTED", res, chk, det, now(), cand["id"]))
        lg.info(f"vet {cand['symbol']} {res} {chk or ''} {det}")

# ------------------------------------------------------------------ BOOK
def book_once(c, lg):
    for cat in C.BOOK_CATEGORIES:
        st, j, lat, err = http_json(f"{C.WM_BASE}/api/prediction/v1/list-prediction-markets?page_size=100&category={cat}")
        if st != 200 or not j: event(c, "book", "BOOK_STOP", f"WM list error {err}"); return
        if not j.get("dataAvailable") or not j.get("fetchedAt"):
            event(c, "book", "BOOK_STOP", "WM dataAvailable=false or fetchedAt=0"); return
        if now() - j["fetchedAt"] / 1000 > C.BOOK_MAX_DATA_AGE_H * 3600:
            event(c, "book", "BOOK_SKIP", "WM market data older than 48h"); continue
        markets = {m.get("title"): m for m in j.get("markets", [])}
        st, f, lat, err = http_json(f"{C.WM_BASE}/api/forecast/v1/get-forecasts")
        fcs = (f or {}).get("forecasts") or []
        if st != 200 or not fcs or (f or {}).get("degraded"):
            event(c, "book", "BOOK_NO_MODEL_PROB", f"no WM forecasts (http {st}, {err}); no own probability -> no bets"); continue
        open_n = c.execute("SELECT COUNT(*) n FROM bets WHERE status IN ('REQUESTED','SIZED','OPEN')").fetchone()["n"]
        calibrated = [fc for fc in fcs if (fc.get("calibration") or {}).get("marketTitle")
                      and (fc.get("calibration") or {}).get("internalProbability") is not None]
        if not calibrated:
            event(c, "book", "BOOK_NO_CALIBRATED", f"{len(fcs)} WM forecasts, 0 with calibration.marketTitle+internalProbability -> no pairable market"); continue
        for fc in calibrated:
            cal = fc.get("calibration") or {}
            title = cal.get("marketTitle"); p = cal.get("internalProbability")
            upd = (fc.get("updatedAt") or 0) / 1000
            if not title or p is None or title not in markets: continue
            if now() - upd > C.BOOK_MAX_DATA_AGE_H * 3600: continue
            m = markets[title]
            st, g, lat, err = http_json(f"{C.GAMMA}/markets?slug={m.get('id')}")
            if st != 200 or not g: continue
            gm = g[0]
            if gm.get("question") != title: continue    # not sure it's the same question -> don't pair
            q = float(json.loads(gm.get("outcomePrices") or "[]")[0])
            edge = p - q
            if abs(edge) <= C.BOOK_MIN_EDGE: continue
            if open_n >= C.BOOK_MAX_OPEN: break
            if c.execute("SELECT 1 FROM bets WHERE venue_id=? AND status IN ('REQUESTED','SIZED','OPEN')", (gm.get("slug"),)).fetchone(): continue
            c.execute("INSERT INTO bets (ts,wm_id,title,venue,venue_id,side,model_prob,model_source,market_price,edge,data_ts,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (now(), m.get("id"), title, "polymarket", gm.get("slug"), "YES" if edge > 0 else "NO", p,
                       "worldmonitor forecast calibration.internalProbability", q, edge, upd, "REQUESTED"))
            open_n += 1

# ------------------------------------------------------------------ SIZE
def size_tick(c, lg):
    # memecoins: only VET-passed candidates
    max_open = getattr(C, "MAX_OPEN_POSITIONS", None)   # variant books C/D only; unset = cash-limited as before
    for cand in c.execute("SELECT * FROM candidates WHERE status='VETTED' AND vet_result IN ('PASS','PASS_PARTIAL')").fetchall():
        d, kr, kc, why = planned_meme_order(c, cand["liquidity"])
        status, reason = "SIZED", why
        n_open = c.execute("SELECT COUNT(*) n FROM positions WHERE status='OPEN' AND kind='meme'").fetchone()["n"] + \
                 c.execute("SELECT COUNT(*) n FROM orders WHERE status='SIZED' AND kind='meme_entry'").fetchone()["n"]
        if max_open and n_open >= max_open:
            status, reason = "ZERO", f"max open positions {max_open} reached"; d = 0
        elif d < C.MIN_ORDER: status, reason = "ZERO", f"size {d:.2f} < min order {C.MIN_ORDER} ({why or 'kelly cap'})"; d = 0
        elif fee_for(d) / d > C.FEE_FLOOR_MAX_EFFECTIVE: status, reason = "ZERO", "fee would exceed 2% of order"; d = 0
        c.execute("""INSERT INTO orders (ts,kind,candidate_id,token,symbol,pair,side,kelly_raw,kelly_capped,dollars,expected_price,status,reason)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (now(), "meme_entry", cand["id"], cand["token"], cand["symbol"], cand["pair"],
                     "BUY", kr, kc, d, cand["price"], status, reason))
        c.execute("UPDATE candidates SET status='SIZED' WHERE id=?", (cand["id"],))
    # one add, only on pullback after confirmed +50%
    for pos in c.execute("SELECT * FROM positions WHERE status='OPEN' AND kind='meme' AND adds=0").fetchall():
        if not pos["last_price"] or not pos["peak_price"]: continue
        if pos["peak_price"] >= pos["entry_price"] * (1 + C.ADD_TRIGGER_GAIN) and \
           pos["last_price"] <= pos["peak_price"] * (1 - C.ADD_PULLBACK) and pos["last_price"] > pos["entry_price"]:
            if c.execute("SELECT 1 FROM orders WHERE position_id=? AND kind='meme_add'", (pos["id"],)).fetchone(): continue
            d, kr, kc, why = planned_meme_order(c, pos["entry_liq"] or 0)
            st = "SIZED" if d >= C.MIN_ORDER else "ZERO"
            c.execute("""INSERT INTO orders (ts,kind,position_id,token,symbol,pair,side,kelly_raw,kelly_capped,dollars,expected_price,status,reason)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (now(), "meme_add", pos["id"], pos["token"], pos["symbol"], pos["pair"],
                         "BUY", kr, kc, d if st == "SIZED" else 0, pos["last_price"], st, why or ("" if st == "SIZED" else "below min order")))
    # prediction bets requested by BOOK
    for b in c.execute("SELECT * FROM bets WHERE status='REQUESTED'").fetchall():
        p, q = b["model_prob"], b["market_price"]
        kr = (p - q) / (1 - q) if b["side"] == "YES" else (q - p) / q
        kc = max(0.0, min(kr, C.KELLY_CAP))
        d = min(kc * equity_now(c), cash(c) - encumbered(c))
        st, why = ("SIZED", "") if d >= C.MIN_ORDER else ("ZERO", f"size {d:.2f} < min order")
        c.execute("""INSERT INTO orders (ts,kind,bet_id,symbol,side,kelly_raw,kelly_capped,dollars,expected_price,status,reason)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (now(), "bet", b["id"], b["title"][:60], b["side"], kr, kc, d if st == "SIZED" else 0,
                     q if b["side"] == "YES" else 1 - q, st, why))
        c.execute("UPDATE bets SET status=? WHERE id=?", ("SIZED" if st == "SIZED" else "ZERO", b["id"]))

# ------------------------------------------------------------------ FILLS
def fills_tick(c, lg):
    for o in c.execute("SELECT * FROM orders WHERE status='SIZED' ORDER BY id").fetchall():
        dollars = o["dollars"]
        if fee_for(dollars) / dollars > C.FEE_FLOOR_MAX_EFFECTIVE:
            c.execute("UPDATE orders SET status='FEE_FLOOR', detail=? WHERE id=?", (f"effective fee {fee_for(dollars)/dollars*100:.2f}%", o["id"])); continue
        if o["kind"] == "bet":
            b = c.execute("SELECT * FROM bets WHERE id=?", (o["bet_id"],)).fetchone()
            st, g, lat, err = http_json(f"{C.GAMMA}/markets?slug={b['venue_id']}")
            if st != 200 or not g:
                c.execute("UPDATE orders SET detail=? WHERE id=?", (f"no price yet: {err}", o["id"])); continue
            gm = g[0]
            ask = float(gm.get("bestAsk") or 0) if b["side"] == "YES" else 1 - float(gm.get("bestBid") or 1)
            if ask <= 0 or ask >= 1:
                c.execute("UPDATE orders SET detail='no usable ask' WHERE id=?", (o["id"],)); continue
            fill_price, filled, liq = ask, dollars, None
        else:
            pair, err = pair_by_address(o["pair"])
            if not pair:
                c.execute("UPDATE orders SET detail=? WHERE id=?", (f"price unavailable, waiting: {err}", o["id"])); continue
            px = float(pair.get("priceUsd") or 0); liq = (pair.get("liquidity") or {}).get("usd") or 0
            if px <= 0 or liq <= 0:
                c.execute("UPDATE orders SET detail='no price/liquidity' WHERE id=?", (o["id"],)); continue
            max_fill = C.SLIPPAGE_LIMIT * (liq / 2.0)       # largest size whose modeled impact stays within 2%
            filled = min(dollars, max_fill)
            if filled < C.MIN_ORDER or fee_for(filled) / filled > C.FEE_FLOOR_MAX_EFFECTIVE:
                c.execute("UPDATE orders SET status='FEE_FLOOR', detail=? WHERE id=?", (f"fillable {filled:.4f} too small for fees", o["id"])); continue
            fill_price = amm_buy(px, filled - fee_for(filled), liq)
        fee = fee_for(filled)
        qty = (filled - fee) / fill_price
        exp = o["expected_price"] or fill_price
        slip = (fill_price - exp) / exp * 1e4
        over = abs(slip) > C.SLIPPAGE_LIMIT * 1e4
        partial = 1 if filled < dollars else 0
        c.execute("BEGIN IMMEDIATE")
        try:
            if o["kind"] == "meme_add":
                pos_id = o["position_id"]
                c.execute("UPDATE positions SET qty=qty+?, cost_usd=cost_usd+?, adds=adds+1 WHERE id=?", (qty, filled, pos_id))
            else:
                kind = "bet" if o["kind"] == "bet" else "meme"
                b = c.execute("SELECT * FROM bets WHERE id=?", (o["bet_id"],)).fetchone() if kind == "bet" else None
                mcap = None
                if kind == "meme":
                    mcap = pair.get("marketCap") or pair.get("fdv")
                cur = c.execute("""INSERT INTO positions (kind,token,symbol,pair,side,market,opened_ts,qty,cost_usd,entry_price,entry_mcap,entry_liq,
                                   peak_price,peak_mcap,last_price,last_mcap,last_ts,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (kind, o["token"], o["symbol"], o["pair"], o["side"], b["venue_id"] if b else None, now(), qty, filled,
                                 fill_price, mcap, liq, fill_price, mcap, fill_price, mcap, now(), "OPEN"))
                pos_id = cur.lastrowid
                if b: c.execute("UPDATE bets SET status='OPEN' WHERE id=?", (b["id"],))
            c.execute("UPDATE account SET cash=cash-? WHERE id=1", (filled,))
            c.execute("""INSERT INTO fills (ts,order_id,position_id,action,token,symbol,requested_usd,filled_usd,partial,expected_price,fill_price,
                         slippage_bps,fee,qty,over_limit,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (now(), o["id"], pos_id, "BUY", o["token"], o["symbol"], dollars, filled, partial, exp, fill_price, slip, fee, qty,
                       int(over), "SLIPPAGE OVER 2% LIMIT" if over else ""))
            c.execute("UPDATE orders SET status=?, position_id=? WHERE id=?", ("PARTIAL" if partial else "FILLED", pos_id, o["id"]))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK"); raise
        if over: event(c, "fills", "SLIPPAGE_OVER_LIMIT", {"order": o["id"], "bps": round(slip, 1)})
        lg.info(f"fill order {o['id']} {o['symbol']} {filled:.2f}/{dollars:.2f} @ {fill_price} slip {slip:.1f}bps partial={partial}")

# ------------------------------------------------------------------ RISK
def close_position(c, pos, price, liq, rule, detail):
    value = pos["qty"] * price
    exit_px = amm_sell(price, value, liq) if (pos["kind"] == "meme" and liq) else price
    gross = pos["qty"] * exit_px
    fee = fee_for(gross) if gross > 0 else 0
    proceeds = max(gross - fee, 0.0)
    c.execute("BEGIN IMMEDIATE")
    c.execute("""UPDATE positions SET status='CLOSED', closed_ts=?, close_rule=?, close_detail=?, proceeds_usd=?, realized_pnl=?,
                 last_price=? WHERE id=? AND status='OPEN'""", (now(), rule, detail, proceeds, proceeds - pos["cost_usd"], price, pos["id"]))
    c.execute("UPDATE account SET cash=cash+? WHERE id=1", (proceeds,))
    c.execute("""INSERT INTO fills (ts,position_id,action,token,symbol,requested_usd,filled_usd,partial,expected_price,fill_price,slippage_bps,fee,qty,over_limit,detail)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (now(), pos["id"], "SELL", pos["token"], pos["symbol"], value, proceeds, 0, price, exit_px,
                 (exit_px - price) / price * 1e4 if price else 0, fee, pos["qty"], int(price and abs(exit_px - price) / price > C.SLIPPAGE_LIMIT), rule))
    if pos["kind"] == "bet": c.execute("UPDATE bets SET status='CLOSED' WHERE venue_id=? AND status='OPEN'", (pos["market"],))
    c.execute("COMMIT")
    event(c, "risk", "CLOSE", {"position": pos["id"], "symbol": pos["symbol"], "rule": rule, "detail": detail})

def risk_measure(pos):
    for attempt in range(1 + C.RISK_RETRIES):
        if pos["kind"] == "meme":
            st, j, lat, err = http_json(f"{C.DEX}/latest/dex/tokens/{pos['token']}")
            if st == 200 and j and j.get("pairs"):
                for p in j["pairs"]:
                    if p.get("pairAddress") == pos["pair"]: return p, None
                err = "position pair not in response"
        else:
            st, j, lat, err = http_json(f"{C.GAMMA}/markets?slug={pos['market']}")
            if st == 200 and j: return j[0], None
        time.sleep(3)
    return None, err

def risk_cycle(c, lg, hb):
    for pos in c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall():
        hb()
        m, err = risk_measure(pos)
        if m is None:
            close_position(c, pos, pos["last_price"] or pos["entry_price"], pos["entry_liq"], "UNMEASURABLE",
                           f"no answer after {C.RISK_RETRIES} retries ({err}); closed at last measured price"); continue
        if pos["kind"] == "meme":
            px = float(m.get("priceUsd") or 0); liq = (m.get("liquidity") or {}).get("usd") or 0
            vol = m.get("volume") or {}; h24 = vol.get("h24") or 0; h6 = vol.get("h6") or 0
            mcap = m.get("marketCap") or m.get("fdv")
            c.execute("UPDATE positions SET last_price=?, last_mcap=?, last_ts=?, peak_price=MAX(COALESCE(peak_price,0),?), peak_mcap=MAX(COALESCE(peak_mcap,0),?) WHERE id=?",
                      (px, mcap, now(), px, mcap or 0, pos["id"]))
            avg6 = h24 / 4
            ratio = (h6 / avg6) if avg6 > 0 else 0.0
            lg.info(f"risk {pos['symbol']} h24={h24} avg_6h={avg6:.2f} h6={h6} ratio={ratio:.3f}")
            if ratio < C.RISK_VOL_RATIO_MIN:
                close_position(c, dict(pos) | {"last_price": px}, px, liq, "VOL_RATIO<0.20",
                               f"volume.h24={h24} avg_6h={avg6:.2f} volume.h6={h6} ratio={ratio:.3f}"); continue
            if mcap and pos["entry_mcap"] and not pos["flagged_60"] and mcap >= pos["entry_mcap"] * (1 + C.RISK_FLAG_MCAP_GAIN):
                c.execute("UPDATE positions SET flagged_60=1 WHERE id=?", (pos["id"],))
                event(c, "risk", "FLAG_MCAP_+60", {"position": pos["id"], "symbol": pos["symbol"], "entry_mcap": pos["entry_mcap"], "mcap": mcap})
        else:
            prices = json.loads(m.get("outcomePrices") or "[]")
            if not prices: continue
            yes = float(prices[0]); px = yes if pos["side"] == "YES" else 1 - yes
            c.execute("UPDATE positions SET last_price=?, last_ts=? WHERE id=?", (px, now(), pos["id"]))
            if m.get("closed"):
                close_position(c, pos, px, None, "MARKET_RESOLVED", f"settled at {px}")

# ------------------------------------------------------------------ main loop
def main(name):
    c = init_db(); lg = logger(name)
    hb = lambda status="ok", detail="": heartbeat(c, name, status, detail)
    hb("starting"); lg.info(f"{name} start pid={os.getpid()}")
    last = 0.0
    while True:
        try:
            if name == "risk":   # RISK keeps running even if desk halted; nobody overrides it
                if now() - last >= C.RISK_INTERVAL_S:
                    last = now(); risk_cycle(c, lg, hb)
                hb("ok", f"next cycle in {max(0, C.RISK_INTERVAL_S - (now()-last)):.0f}s")
            elif halted(c):
                hb("halted", "desk halted by CHIEF")
            elif name == "scan":
                if now() - last >= C.SCAN_INTERVAL_S: last = now(); scan_once(c, lg)
                hb()
            elif name == "vet": vet_tick(c, lg, hb); hb()
            elif name == "size": size_tick(c, lg); hb()
            elif name == "fills": fills_tick(c, lg); hb()
            elif name == "book":
                if degraded(c): hb("resting", "World Monitor degraded -> BOOK rests")
                else:
                    if now() - last >= C.BOOK_INTERVAL_S: last = now(); book_once(c, lg)
                    hb()
        except Exception as e:
            lg.error(traceback.format_exc()); event(c, name, "ERROR", f"{type(e).__name__}: {e}")
            hb("error", f"{type(e).__name__}: {e}")
        time.sleep(5)

if __name__ == "__main__":
    assert sys.argv[1] in C.BOTS
    main(sys.argv[1])
