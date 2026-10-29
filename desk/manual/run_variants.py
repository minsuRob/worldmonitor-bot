"""PAPER-ONLY variant runner: BASE + A/B/C/D as five INDEPENDENT $1,000 paper books.

  python3 manual/run_variants.py prepare            -> one shared DexScreener fetch; then PER BOOK: own 60-min seen-recently and
                                                       already-held filter, own candidates, own VET; one Claude judge job per
                                                       (book, token that passed that book's VET), id <runId>:<book>:<mint>, with the
                                                       book's equity/cash/open positions/planned order/rules + macro context.
                                                       Prints JSON {runId, jobs, jobsFile, ...}. jobs==0 -> no Mac step needed.
  python3 manual/run_variants.py finish <runId>     -> import Mac results (import-results.mjs), map each result back to its book,
                                                       apply decisions per book, SIZE + FILLS + RISK per book, equity snapshot.
  python3 manual/run_variants.py finish <runId> --no-judge   (Mac asleep / runner failed: nothing is bought, RISK still runs)
  Job cap: env CLAUDE_CLI_MAX_JOBS (default 40) for the whole cycle, filled round-robin by rank across books; the rest are
  recorded per book as OVER_JOB_CAP. The Mac runner must use the same CLAUDE_CLI_MAX_JOBS.
  Shared raw data only: the DexScreener fetch and holder lookups (RPC/RugCheck/Helius DAS) are memoized per mint per cycle;
  api_calls in the cycle record shows Helius requests vs unique keys (repeats should be 0 apart from retries).
  runId = meme-var-YYYYMMDD-HHMMSS. prepare/finish hold state/variants.lock (flock); a second one exits 3. prepare refuses
  a runId that already has a cycle file, run dir or vcycles row; finish refuses a runId already finished.

Books (rules in manual/book_rules.py; shared RISK identical everywhere and never loosened, C/D only ADD exits after it):
  BASE  existing ledger state/desk.db, rules from config.py, Claude BUY/SKIP
  A     Claude EV rule on its own job: BUY iff p_win*payoff_ratio - (1-p_win) - 0.03 > 0   (VET = BASE)
  B     VET_TOP_HOLDER_MAX 0.05 -> 0.08 (the old C book, moved 2026-10-29)
  C     AGGRESSIVE momentum rider: h1 +10%..+150%, h6 >= 0, m5 > -8%, m5 buys >= sells, top holder 8%; fixed 10% size, max 5 open;
        EV buy rule (as A); exits stop -20%, sell 50% at 2x, trail 25% from peak
  D     AGGRESSIVE early sniper: pair age 5m..24h, liq >= $5k, top holder 10%, >= 50 holders, m5 buys/sells >= 1.3 (>= 10 buys),
        5m volume pace >= 1.2x 1h pace, m5 > -15%, h1 < 300%; quote token SOL/USDC/USDT only (D_quote_not_sol);
        no chasing: reject a >= 2.5x run within 30 min on GeckoTerminal 1m candles (D_run30_ge_2.5x; fetch failure -> D_run30_unknown,
        fail closed; fetched only for candidates that passed every other D check); fixed 5% size, max 10 open, 4% round-trip slippage budget;
        numeric signal buys, Claude is a rug VETO only (own system prompt); exits stop -35%, sell 50% at 3x, trail 40% from peak
Books A-D: state/variants/<V>.db (same schema as desk.db, each started at $1,000.00 paper).
No wallets, signing keys, orders or execution calls: DexScreener / RugCheck / Solana RPC (Helius first, key from
env HELIUS_API_KEY via config.py -> desk .env) reads only.
"""
import sys, os, json, time, hashlib, datetime, subprocess, contextlib, sqlite3, fcntl
HERE = os.path.dirname(os.path.abspath(__file__)); DESK = os.path.dirname(HERE)
sys.path.insert(0, DESK)
import config as C
import common
from common import *
import bots
import regime_context   # manual/regime_context.py: macro block for the judge prompt (context only)
import book_rules as BR  # manual/book_rules.py: per-book overrides, prechecks, buy rule, exits

VARIANTS = ["BASE", "A", "B", "C", "D"]
OVERRIDES = BR.OVERRIDES
A_ROUNDTRIP_COST = BR.ROUNDTRIP_COST
MAX_JOBS = int(os.environ.get("CLAUDE_CLI_MAX_JOBS", "40"))   # whole cycle, all books (runner cap must match)
VDIR = os.path.join(C.STATE, "variants"); os.makedirs(VDIR, exist_ok=True)
CYCLES_DIR = os.path.join(HERE, "variant_cycles"); os.makedirs(CYCLES_DIR, exist_ok=True)
WM = "/workspace/worldmonitor"
STORE = f"{WM}/data/claude-cli"
EXTRA = """CREATE TABLE IF NOT EXISTS vcycles (id INTEGER PRIMARY KEY, run_id TEXT UNIQUE, variant TEXT, ts_prepare REAL, ts_finish REAL,
  scanned INTEGER, passed INTEGER, buys INTEGER, fills INTEGER, closes INTEGER, judged INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS vjudge (id INTEGER PRIMARY KEY, run_id TEXT, candidate_id INTEGER, token TEXT, symbol TEXT, job_id TEXT,
  claude_decision TEXT, confidence REAL, p_win REAL, payoff_ratio REAL, ev REAL, variant_decision TEXT, rule TEXT, rationale TEXT, ts REAL);"""

def vdb(v):
    if v == "BASE":
        c = init_db()
    else:
        c = sqlite3.connect(os.path.join(VDIR, f"{v}.db"), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000")
        c.executescript(common.SCHEMA)
        if not c.execute("SELECT 1 FROM account").fetchone():
            c.execute("INSERT INTO account VALUES (1,?,?,?)", (C.START_BALANCE, C.START_BALANCE, now()))
    c.executescript(EXTRA)
    if v != "BASE": c.executescript(BR.EXTRA_SQL)   # partial take-profit state (C/D exits); not added to desk.db
    return c

@contextlib.contextmanager
def rules(v):
    old = {k: getattr(C, k) for k in OVERRIDES[v]}
    for k, val in OVERRIDES[v].items(): setattr(C, k, val)
    try: yield
    finally:
        for k, val in old.items(): setattr(C, k, val)

# ---- one-cycle caches so every variant sees identical data (holders, pair re-measure, marks)
_cache = {}
def _memo(name, fn):
    def w(*a):
        key = (name,) + tuple(x for x in a if isinstance(x, str))
        if key not in _cache: _cache[key] = fn(*a)
        return _cache[key]
    return w
bots.top_holders_rpc = _memo("rpc", bots.top_holders_rpc)
bots.top_holders_rugcheck = _memo("rug", bots.top_holders_rugcheck)
bots.pair_by_address = _memo("pair", bots.pair_by_address)
bots.holder_count_helius = _memo("hcount", bots.holder_count_helius)   # Helius DAS, once per token per cycle
_risk_measure_raw = bots.risk_measure
def _risk_measure(pos):
    key = ("mark", pos["token"], pos["pair"])
    if key not in _cache: _cache[key] = _risk_measure_raw(pos)
    return _cache[key]
bots.risk_measure = _risk_measure
def clear_cache(): _cache.clear()

# ---- API call accounting (Helius credit sanity check): per-book filtering must not multiply Helius calls
API_CALLS, HELIUS_KEYS = {}, {}
_http_raw = bots.http_json
def _http_counted(url, method="GET", body=None, *a, **k):
    if C.HELIUS_RPC and url == C.HELIUS_RPC:
        m = (body or {}).get("method"); prm = (body or {}).get("params")
        if isinstance(prm, list): key = json.dumps(prm[0])[:200] if prm else ""
        elif isinstance(prm, dict): key = f"{prm.get('mint')}|page={prm.get('page')}"
        else: key = ""
        label = f"helius:{m}"; HELIUS_KEYS[f"{m}|{key}"] = HELIUS_KEYS.get(f"{m}|{key}", 0) + 1
    else:
        label = url.split("?")[0].replace("https://", "").split("/")[0]
    API_CALLS[label] = API_CALLS.get(label, 0) + 1
    return _http_raw(url, method, body, *a, **k)
bots.http_json = _http_counted

def api_call_report():
    """Helius requests vs unique (method, mint[, page]) keys. repeats > 0 means a retry or a cache miss."""
    reqs = sum(HELIUS_KEYS.values())
    return {"by_host": dict(API_CALLS),
            "helius_summary": {"requests": reqs, "unique_keys": len(HELIUS_KEYS),
                               "repeats": reqs - len(HELIUS_KEYS),
                               "repeated_keys": sorted(k.split("|")[0] for k, n in HELIUS_KEYS.items() if n > 1)}}

def _fix_detail(det):
    # bots.vet_one hardcodes ">5%" in the reject text; show the variant's actual limit
    return det.replace("largest holder >5%:", f"largest holder >{C.VET_TOP_HOLDER_MAX*100:.0f}%:", 1) if det else det

LOCK_PATH = os.path.join(C.STATE, "variants.lock")

@contextlib.contextmanager
def cycle_lock(what):
    """One prepare/finish at a time across routine + manual runs (flock, released automatically if the process dies)."""
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        held = os.pread(fd, 300, 0).decode(errors="replace").strip()
        os.close(fd)
        sys.stderr.write(f"variants: another prepare/finish holds {LOCK_PATH} ({held or 'unknown holder'}); refusing {what}\n")
        sys.exit(3)
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"pid={os.getpid()} {what} since {kst_str(time.time())}".encode(), 0)
    try:
        yield
    finally:
        os.ftruncate(fd, 0); fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)

def run_id_in_use(run_id):
    if os.path.exists(os.path.join(CYCLES_DIR, f"{run_id}.json")) or os.path.exists(os.path.join(STORE, run_id)):
        return True
    return any(vdb(v).execute("SELECT 1 FROM vcycles WHERE run_id=?", (run_id,)).fetchone() for v in VARIANTS)

SYSTEM = """You are the JUDGE for ONE paper book of a PAPER-ONLY (simulated) Solana memecoin desk. No real money is involved.
Each book is an independent paper account that started with $1,000, with its own rules, cash and open positions. You are given THIS book's state and rules; the token has passed THIS book's screening.
Using ONLY the data given, decide whether THIS book should open its planned small paper long now (consider its cash and what it already holds).
Return ONLY one JSON object, no prose, exactly:
{"decision":"BUY"|"SKIP","confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}
p_win = probability the trade hits a win before a loss over the next ~24h; payoff_ratio = average win / average loss.
Give honest p_win and payoff_ratio estimates even when you SKIP. Be skeptical: most new memecoins go to zero. Prefer SKIP when data is thin or signals conflict."""

def book_rules_text(v):
    """Plain-words rule set of book v (call inside rules(v) so the numbers are the book's own)."""
    k_raw = C.MEME_ASSUMED_P_WIN - (1 - C.MEME_ASSUMED_P_WIN) / C.MEME_ASSUMED_PAYOFF_B
    screen = (f"Screening: largest holder <= {C.VET_TOP_HOLDER_MAX*100:.0f}% of supply (pool vaults excluded); liquidity >= ${C.VET_MIN_LIQ:,.0f} "
              f"and >= {C.VET_LIQ_MULT:.0f}x the order; reject if price rose >= {C.VET_PRICE_UP_PCT:g}% while holder count grew < {C.VET_HOLDERS_FLAT_PCT:g}%; "
              f"1h price change < {C.VET_H1_ALREADY_PRICED:g}%; positive assumed edge after fees; pairs younger than {C.VET_MIN_AGE_MIN} min must not be losing liquidity.")
    diff, buy, exits = BR.describe(v)
    if C.SIZE_FIXED_FRACTION:
        size = (f"Sizing: fixed {C.SIZE_FIXED_FRACTION*100:.0f}% of equity, limited by free cash, liquidity/{C.VET_LIQ_MULT:.0f}, a {C.SLIPPAGE_BUDGET*100:.0f}% "
                f"round-trip slippage budget and max {C.MAX_OPEN_POSITIONS} open positions. {exits}")
    else:
        size = (f"Sizing: Kelly {k_raw*100:.2f}% (assumed p={C.MEME_ASSUMED_P_WIN}, b={C.MEME_ASSUMED_PAYOFF_B}) capped at {C.KELLY_CAP*100:.0f}% of equity, "
                f"limited by free cash, liquidity/{C.VET_LIQ_MULT:.0f} and a 2% round-trip slippage budget. Exits (RISK) are the desk's standard rules, same in every book.")
    return f"{diff} {screen} {size} {buy}"

def book_state(c):
    rows, mv, unr = mark_positions(c)
    cash_ = cash(c)
    pos = [{"symbol": r["symbol"], "mint": r["token"], "entryPrice": r["entry_price"], "lastPrice": r["last_price"],
            "costUsd": round(r["cost_usd"] or 0, 2), "unrealizedUsd": round((r["qty"] or 0) * (r["last_price"] or 0) - (r["cost_usd"] or 0), 2)}
           for r in c.execute("SELECT * FROM positions WHERE status='OPEN'")]
    return {"startUsd": C.START_BALANCE, "equityUsd": round(cash_ + mv, 2), "cashUsd": round(cash_, 2),
            "unencumberedCashUsd": round(cash_ - encumbered(c), 2), "openPositions": pos}

def prepare():
    t0 = time.time()
    run_id = "meme-var-" + kst().strftime("%Y%m%d-%H%M%S")   # seconds: two runs in one minute no longer collide
    if run_id_in_use(run_id): sys.exit(f"{run_id} already exists (cycle file, run dir or vcycles row); refusing to reuse it")
    lg = logger("variants")
    fetched = bots.scan_fetch(lg)           # ONE shared DexScreener fetch (raw data only)
    t_scan = time.time()
    out = {"run_id": run_id, "mode": "independent-books", "scan_ts": t0, "scan_kst": kst_str(t0),
           "scan_last": {"ts": t_scan, "tokens": len(fetched["tokens"]), "pairs": len(fetched["pairs"]), "errors": fetched["errs"] + fetched["perrs"]},
           "books": {}, "candidates": [], "variants": {}}
    seen_tok = set(); per_book = {}
    for v in VARIANTS:                      # each book: own seen-recently / held filter, own candidates, own VET
        c = vdb(v); res_list = []
        before = c.execute("SELECT COALESCE(MAX(id),0) m FROM candidates").fetchone()["m"]
        dbefore = c.execute("SELECT COALESCE(MAX(id),0) m FROM scan_drops").fetchone()["m"]
        with rules(v): bots.scan_filter(c, lg, fetched)
        drops = [dict(r) for r in c.execute("SELECT token,symbol,pair,reason FROM scan_drops WHERE id>?", (dbefore,))]
        cands = [dict(r) for r in c.execute("SELECT * FROM candidates WHERE id>? ORDER BY score DESC", (before,))]
        held = {r["token"] for r in c.execute("SELECT token FROM positions WHERE status='OPEN'")}
        cinfo = []
        for cand in cands:
            p = json.loads(cand["data"])
            ci = {k: cand[k] for k in ("id", "token", "symbol", "pair", "dex", "price", "liquidity", "fdv", "mcap", "pair_created", "score")} \
                 | {"url": p.get("url"), "volume": p.get("volume"), "txns": p.get("txns"), "priceChange": p.get("priceChange")}
            cinfo.append(ci)
            if cand["token"] not in seen_tok: seen_tok.add(cand["token"]); out["candidates"].append(ci)
        with rules(v):
            for cand, ci in zip(cands, cinfo):
                row = c.execute("SELECT * FROM candidates WHERE id=?", (cand["id"],)).fetchone()
                run30 = None
                pre = BR.precheck(v, json.loads(cand["data"]), cand["pair_created"], t0)   # numeric, no API calls
                if cand["token"] in held:
                    r_, chk, det = "REJECT", "0_already_held", "this book already holds this token"
                elif pre:
                    r_, (chk, det) = "REJECT", pre
                else:
                    try:
                        r_, chk, det = bots.vet_one(c, row, lg)
                        post = BR.postcheck(v, c.execute("SELECT holders FROM candidates WHERE id=?", (cand["id"],)).fetchone()["holders"]) if r_ != "REJECT" else None
                        if post: r_, (chk, det) = "REJECT", post
                        if r_ != "REJECT" and BR.PARAMS[v].get("run30"):   # D: 1m candles, only for candidates that passed everything else
                            rej, run30 = BR.run30_check(v, cand["pair"], t0, lg)
                            if rej: r_, (chk, det) = "REJECT", rej
                    except Exception as e: r_, chk, det = "REJECT", "error", f"{type(e).__name__}: {e}"
                det = _fix_detail(det)
                c.execute("UPDATE candidates SET status=?, vet_result=?, vet_check=?, vet_detail=?, vet_ts=? WHERE id=?",
                          ("JUDGE_PENDING" if r_ != "REJECT" else "REJECTED", r_, chk, det, now(), cand["id"]))
                order, k_raw, k_cap, oreason = bots.planned_meme_order(c, cand["liquidity"])
                res_list.append({"cand": cand["id"], "vid": cand["id"], "token": cand["token"], "symbol": cand["symbol"], "score": cand["score"],
                                 "vet_result": r_, "vet_check": chk, "vet_detail": det, "planned_order": round(order, 2),
                                 "order_reason": oreason, "kelly_capped": k_cap, "_ci": ci} | ({"run30": run30} if run30 else {}))
                lg.info(f"[{run_id}] {v} vet {cand['symbol']} {r_} {chk or ''} {det}")
            out["books"][v] = {"scan_kept": len(cands), "scan_drops": drops, "state": book_state(c), "rules": book_rules_text(v)}
        c.execute("INSERT OR REPLACE INTO vcycles (run_id,variant,ts_prepare,scanned,passed) VALUES (?,?,?,?,?)",
                  (run_id, v, t0, len(cands), sum(1 for r in res_list if r["vet_result"] != "REJECT")))
        per_book[v] = [r for r in res_list if r["vet_result"] != "REJECT"]
        out["variants"][v] = [{k: val for k, val in r.items() if k != "_ci"} for r in res_list]
    t_vet = time.time()
    # per-book judge jobs (no cross-book dedup); cap shared round-robin by rank so overflow is spread across books
    order_q = []
    for rank in range(max([len(x) for x in per_book.values()] + [0])):
        for v in VARIANTS:
            if rank < len(per_book[v]): order_q.append((v, per_book[v][rank]))
    judged, unjudged = order_q[:MAX_JOBS], order_q[MAX_JOBS:]
    rundir = os.path.join(STORE, run_id); os.makedirs(rundir, exist_ok=True)
    regime_block, regime_rows = regime_context.build() if judged else ("", [])   # once per cycle, same text in every job
    out["regime_context"] = {"block": regime_block, "rows": regime_rows}
    jobs = []
    for v, r in judged:
        cand = r["_ci"]
        with rules("BASE"):   # cached raw holder data (no new fetch)
            ok, hdet = bots.check_top_holder({"token": cand["token"], "pair": cand["pair"]}, lg)
        hdet = (hdet or "").replace("largest holder >5%:", "largest holder", 1)
        hc = bots.holder_count_helius(cand["token"], lg)   # memoized per mint per cycle
        hcount = (f"{'>=' if hc[1] else ''}{hc[0]} token accounts with balance ({hc[3]})" if hc else "unknown (holder count unavailable)")
        v_ = cand["volume"] or {}
        data = {"symbol": cand["symbol"], "mint": cand["token"], "pair": cand["pair"], "dex": cand["dex"],
                "priceUsd": cand["price"], "liquidityUsd": cand["liquidity"], "fdvUsd": cand["fdv"], "marketCapUsd": cand["mcap"],
                "pairAgeHours": round((t0 - cand["pair_created"]) / 3600, 2) if cand["pair_created"] else None,
                "volumeUsd": {k: v_.get(k) for k in ("h24", "h6", "h1", "m5")},
                "txns": cand["txns"], "priceChangePct": cand["priceChange"],
                "holderConcentration": hdet, "holderCount": hcount, "scanMomentumScore": cand["score"]}
        bk = out["books"][v]
        book = {"book": v, **bk["state"], "plannedOrderUsd": r["planned_order"],
                "plannedOrderNote": r["order_reason"] or f"{r['kelly_capped']*100:.2f}% of equity", "vet": f"{r['vet_result']} {r['vet_detail'] or ''}".strip()}
        user = (f"Paper book {v} (independent $1,000 account) state:\n" + json.dumps(book, indent=1, ensure_ascii=False)
                + f"\nBook {v} rules: {bk['rules']}\n\n"
                + f"Market data snapshot (DexScreener, {out['scan_kst']}):\n" + json.dumps(data, indent=1, ensure_ascii=False))
        if regime_block: user += "\n\n" + regime_block
        sysp = BR.D_SYSTEM if BR.PARAMS[v]["buy"] == "veto" else SYSTEM
        job = {"id": f"{run_id}:{v}:{cand['token']}", "runId": run_id, "pipeline": "memecoin", "stage": "judge", "book": v,
               "promptHash": hashlib.sha256((sysp + "\0" + user).encode()).hexdigest()[:16],
               "openrouterModel": None, "openrouterCacheKey": None, "maxTokens": 400, "responseFormat": "json_object",
               "system": sysp, "user": user, "capturedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
               "candidateId": cand["id"], "token": cand["token"], "symbol": cand["symbol"]}
        jobs.append(job)
    jobs_file = os.path.join(rundir, "jobs.jsonl")
    with open(jobs_file, "w") as f:
        for j in jobs: f.write(json.dumps(j, ensure_ascii=False) + "\n")
    out["jobs"] = [{"id": j["id"], "book": j["book"], "token": j["token"], "symbol": j["symbol"]} for j in jobs]
    out["unjudged_over_cap"] = [{"book": v, "token": r["token"], "symbol": r["symbol"]} for v, r in unjudged]
    out["max_jobs"] = MAX_JOBS
    out["api_calls"] = api_call_report()
    out["timing_s"] = {"scan": round(t_scan - t0, 1), "filter_vet_all_books": round(t_vet - t_scan, 1)}
    json.dump(out, open(os.path.join(CYCLES_DIR, f"{run_id}.json"), "w"), indent=1, default=str, ensure_ascii=False)
    print(json.dumps({"runId": run_id, "jobs": len(jobs), "jobsFile": jobs_file,
                      "candidates": {v: out["books"][v]["scan_kept"] for v in VARIANTS},
                      "passed": {v: len(per_book[v]) for v in VARIANTS},
                      "unjudgedOverCap": len(unjudged), "helius": out["api_calls"]["helius_summary"], "timing_s": out["timing_s"]}))

def finish(run_id, no_judge=False):
    t0 = time.time(); lg = logger("variants")
    cyc_path = os.path.join(CYCLES_DIR, f"{run_id}.json")
    cyc = json.load(open(cyc_path))
    done = vdb("BASE").execute("SELECT ts_finish FROM vcycles WHERE run_id=?", (run_id,)).fetchone()
    if done and done["ts_finish"]: sys.exit(f"{run_id} already finished at {kst_str(done['ts_finish'])}; not applying twice")
    rundir = os.path.join(STORE, run_id)
    decisions, judge_note = {}, ""
    if cyc.get("jobs") and not no_judge:
        if not os.path.exists(os.path.join(rundir, "results.jsonl")):
            sys.exit(f"results.jsonl missing in {rundir}; copy it from the Mac or use --no-judge")
        r = subprocess.run(["node", "scripts/claude-cli/import-results.mjs", "--run-id", run_id], cwd=WM, capture_output=True, text=True)
        judge_note = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else f"import rc={r.returncode}"
        if r.returncode != 0: sys.exit(f"import failed: {r.stdout}{r.stderr}")
        for line in open(os.path.join(rundir, "stored.jsonl")):
            if not line.strip(): continue
            rec = json.loads(line); pj = rec.get("parsedJson") if rec.get("ok") else None
            job = next(j for j in cyc["jobs"] if j["id"] == rec["jobId"])
            decisions[(job.get("book"), job["token"])] = {"job_id": rec["jobId"], "ok": rec.get("ok"), "json": pj, "durationMs": rec.get("durationMs"),
                                       "model": rec.get("claudeModel"), "apiKeySource": rec.get("apiKeySource")}
    elif no_judge: judge_note = "NO_JUDGE: Mac step skipped; nothing bought this cycle"
    summary = {"run_id": run_id, "scan_kst": cyc["scan_kst"], "judge": judge_note, "claude": {}, "variants": {}}
    for (bk, tok), d in decisions.items():
        j = d["json"] or {}
        summary["claude"].setdefault(bk, {})[tok] = {"symbol": next(c_["symbol"] for c_ in cyc["candidates"] if c_["token"] == tok), "job_id": d["job_id"],
                                  "decision": j.get("decision"), "confidence": j.get("confidence"), "p_win": j.get("p_win"),
                                  "payoff_ratio": j.get("payoff_ratio"), "rationale": j.get("rationale"), "ms": d["durationMs"],
                                  "model": d["model"], "apiKeySource": d["apiKeySource"], "parse_ok": bool(d["json"])}
    t_imp = time.time()
    clear_cache()   # fresh marks for this FILLS/RISK pass, shared by all books
    for v in VARIANTS:
        c = vdb(v); vs = {"vet": [], "decisions": [], "orders": [], "fills": [], "risk": []}
        with rules(v):
            for r_ in cyc["variants"][v]:
                vs["vet"].append({k: r_[k] for k in ("symbol", "token", "vet_result", "vet_check", "vet_detail", "planned_order")}
                                 | ({"run30": r_["run30"]} if r_.get("run30") else {}))
                if r_["vet_result"] == "REJECT": continue
                d = decisions.get((v, r_["token"])); j = (d or {}).get("json")
                if not j:
                    why = "NO_JUDGE" if (no_judge or not d) else "JUDGE_UNPARSEABLE"
                    if any(u["token"] == r_["token"] and u.get("book", v) == v for u in cyc.get("unjudged_over_cap", [])): why = "OVER_JOB_CAP"
                    dec, rule, ev = "SKIP", why, None
                else:
                    dec, rule, ev = BR.decide(v, j)   # BASE/B: Claude word; A/C: EV>0; D: numeric signal unless Claude vetoes
                c.execute("""INSERT INTO vjudge (run_id,candidate_id,token,symbol,job_id,claude_decision,confidence,p_win,payoff_ratio,ev,variant_decision,rule,rationale,ts)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id, r_["vid"], r_["token"], r_["symbol"], (d or {}).get("job_id"),
                             (j or {}).get("decision"), (j or {}).get("confidence"), (j or {}).get("p_win"), (j or {}).get("payoff_ratio"), ev, dec, rule,
                             (j or {}).get("rationale"), now()))
                c.execute("UPDATE candidates SET status=? WHERE id=?", ("VETTED" if dec == "BUY" else "CLAUDE_SKIP", r_["vid"]))
                vs["decisions"].append({"symbol": r_["symbol"], "token": r_["token"], "decision": dec, "rule": rule, "ev": ev,
                                        "claude": (j or {}).get("decision"), "confidence": (j or {}).get("confidence"),
                                        "p_win": (j or {}).get("p_win"), "payoff_ratio": (j or {}).get("payoff_ratio"),
                                        "rationale": (j or {}).get("rationale"), "ms": (d or {}).get("durationMs")})
            o_before = c.execute("SELECT COALESCE(MAX(id),0) m FROM orders").fetchone()["m"]
            f_before = c.execute("SELECT COALESCE(MAX(id),0) m FROM fills").fetchone()["m"]
            bots.size_tick(c, lg)       # SIZE (only BUY-judged candidates are VETTED)
            bots.fills_tick(c, lg)      # FILLS (desk slippage model at current DexScreener price)
            f_mid = c.execute("SELECT COALESCE(MAX(id),0) m FROM fills").fetchone()["m"]
            bots.risk_cycle(c, lg, lambda *a: None)   # RISK: identical rules in every book
            vs["book_exits"] = BR.book_exits(c, v, lg, bots.close_position,   # C/D only: stop / partial TP / trail on RISK's fresh marks
                                             lambda p_: ((bots.risk_measure(p_)[0] or {}).get("liquidity") or {}).get("usd"))
            for o in c.execute("SELECT * FROM orders WHERE id>?", (o_before,)):
                vs["orders"].append({k: o[k] for k in ("id", "kind", "symbol", "token", "dollars", "kelly_raw", "kelly_capped", "expected_price", "status", "reason", "detail")})
            for f in c.execute("SELECT * FROM fills WHERE id>?", (f_before,)):
                pos = c.execute("SELECT pair FROM positions WHERE id=?", (f["position_id"],)).fetchone()
                rec = {k: f[k] for k in ("action", "symbol", "token", "requested_usd", "filled_usd", "expected_price", "fill_price", "slippage_bps", "fee", "qty", "partial", "detail")}
                rec["pair_url"] = f"https://dexscreener.com/solana/{pos['pair']}" if pos else None
                (vs["fills"] if f["id"] <= f_mid else vs["risk"]).append(rec)
            opens = c.execute("SELECT symbol,last_price,entry_price,qty,cost_usd FROM positions WHERE status='OPEN'").fetchall()
            vs["risk_open_marks"] = [dict(o) | {"mark_pnl": (o["qty"] * (o["last_price"] or 0)) - o["cost_usd"]} for o in opens]
            # equity snapshot (mark = qty*last_price, same as common.mark_positions)
            rows, mv, unr = mark_positions(c)
            realized = c.execute("SELECT COALESCE(SUM(realized_pnl),0) s FROM positions WHERE status='CLOSED'").fetchone()["s"]
            cash_ = cash(c)
            c.execute("INSERT INTO equity (ts,cash,equity,realized,unrealized,deployed) VALUES (?,?,?,?,?,?)",
                      (now(), cash_, cash_ + mv, realized, unr, sum(r["cost_usd"] or 0 for r in rows)))
            vs["equity"] = round(cash_ + mv, 2); vs["cash"] = round(cash_, 2)
            buys = sum(1 for d_ in vs["decisions"] if d_["decision"] == "BUY")
            c.execute("UPDATE vcycles SET ts_finish=?, buys=?, fills=?, closes=?, judged=?, note=? WHERE run_id=?",
                      (now(), buys, len(vs["fills"]), len(vs["risk"]), sum(1 for d_ in vs["decisions"] if d_["rule"] not in ("NO_JUDGE", "OVER_JOB_CAP", "JUDGE_UNPARSEABLE")),
                       judge_note[:200], run_id))
        summary["variants"][v] = vs
        lg.info(f"[{run_id}] {v} buys={buys} fills={len(vs['fills'])} risk_closes={len(vs['risk'])} equity={vs['equity']}")
    summary["api_calls_prepare"] = cyc.get("api_calls"); summary["api_calls_finish"] = api_call_report()
    summary["timing_s"] = cyc.get("timing_s", {}) | {"import": round(t_imp - t0, 1), "size_fills_risk_all": round(time.time() - t_imp, 1)}
    json.dump(summary, open(os.path.join(CYCLES_DIR, f"{run_id}.result.json"), "w"), indent=1, default=str, ensure_ascii=False)
    if "--json" in sys.argv: print(json.dumps(summary, indent=1, default=str, ensure_ascii=False)); return
    print_brief(summary)

def print_brief(summary):
    print(f"{summary['run_id']} scan {summary['scan_kst']} | {summary['judge']}")
    for bk, toks in summary["claude"].items():
      for tok, j in toks.items():
        print(f"  claude {bk} {j['symbol']} {tok}: {j['decision']} conf={j['confidence']} p_win={j['p_win']} b={j['payoff_ratio']} {j['ms']}ms {j['model']} key={j['apiKeySource']}")
    for v, vs in summary["variants"].items():
        rej = {}
        for r_ in vs["vet"]:
            if r_["vet_result"] == "REJECT": rej[r_["vet_check"]] = rej.get(r_["vet_check"], 0) + 1
        print(f"  {v}: cands={len(vs['vet'])} passed={len(vs['decisions'])} rejects={rej} "
              f"buys={[d['symbol'] for d in vs['decisions'] if d['decision']=='BUY']} fills={len(vs['fills'])} "
              f"risk_closes={len(vs['risk'])} open={len(vs['risk_open_marks'])} equity=${vs['equity']:.2f}")
        for d in vs["decisions"]:
            print(f"     {d['symbol']}: {d['decision']} ({d['rule']}) claude={d['claude']} conf={d['confidence']} p_win={d['p_win']} b={d['payoff_ratio']}"
                  + (f" EV={d['ev']:.4f}" if isinstance(d.get('ev'), (int, float)) else ""))
        for f in vs["fills"]:
            print(f"     FILL {f['symbol']} {f['token']} {f['pair_url']} req=${f['requested_usd']:.2f} filled=${f['filled_usd']:.2f} "
                  f"exp={f['expected_price']} px={f['fill_price']} slip={f['slippage_bps']:.1f}bps fee=${f['fee']:.2f}")
        for f in vs["risk"]:
            print(f"     RISK CLOSE {f['symbol']} {f['detail']} px={f['fill_price']} proceeds=${f['filled_usd']:.2f}")
    print(f"  timing_s {summary['timing_s']}  full: {os.path.join(CYCLES_DIR, summary['run_id'] + '.result.json')}")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "prepare":
        with cycle_lock("prepare"): prepare()
    elif len(a) >= 2 and a[0] == "finish":
        with cycle_lock(f"finish {a[1]}"): finish(a[1], "--no-judge" in a)
    else: sys.exit(__doc__)
