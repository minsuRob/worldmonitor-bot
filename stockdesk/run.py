"""PAPER-ONLY stock desk runner (box side). Pattern: desk/manual/run_variants.py (locks, prepare/finish split, memoized data).

  python3 run.py prepare <slot>              screens for every strategy in the slot; LLM books -> jobs.jsonl, numeric books -> PENDING orders
  python3 run.py finish <runId> [--no-judge] reads results.jsonl (Mac runner) -> decide -> PENDING orders
  python3 run.py slot <name>                 fill slot: marks -> RISK -> fill PENDING -> strategy exits -> equity snapshot
  python3 run.py due [--run]                 code-only slots whose window is open and not yet run today (box cron)

Ledgers: state/books/<CODE>.db, one per strategy (registry). The shared market cache is state/market.db.
RISK (risk.py) always runs before any strategy code and bans are re-applied after screen(); strategies cannot skip either.
"""
import contextlib, fcntl, json, os, sys, time, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import config as C
import common
from common import now, kst_str, open_db, kv_get, kv_set, event, cash, encumbered, equity_now, mark_value, open_positions
import marketdb as M
import schedule as S
import screen as SC
import fills as F
import risk as R
import judge as J
import regime_context
import strategies
from strategies.base import Ctx

LOG = common.logger("stockdesk")
STORE = C.CLAUDE_CLI_STORE

# ---- ledgers
_dbs = {}
def vdb(code):
    if code in _dbs: return _dbs[code]
    st = strategies.by_code(code)
    c = open_db(os.path.join(C.BOOKS_DIR, f"{code}.db"))
    c.executescript(common.BOOK_SCHEMA); common.migrate(c)
    if st.extra_sql(): c.executescript(st.extra_sql())
    if not c.execute("SELECT 1 FROM account").fetchone():
        if st.currency == "KRW":
            bal = C.START_BALANCE_KRW
        else:
            bal, rate, cost_krw = F.fx_convert_once(C.START_BALANCE_KRW)
            kv_set(c, "fx_start", {"krw_per_usd": rate, "krw": C.START_BALANCE_KRW, "usd": bal, "cost_krw": cost_krw, "ts": now()})
        c.execute("INSERT INTO account VALUES (1,?,?,?,?)", (bal, bal, st.currency, now()))
        if st.currency == "USD":
            c.execute("INSERT INTO fills (ts,action,market,code,qty,price,value,fee,tax,other_fee,partial,liquidity_ref,source,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (now(), "FX_FUND", "US", "USDKRW", bal, rate, C.START_BALANCE_KRW, 0, 0, cost_krw, 0, "config", "fx_convert_once", f"{C.START_BALANCE_KRW:.0f} KRW -> {bal:.2f} USD @ {rate}"))
        event(c, "BOOK", "OPEN", {"book": code, "currency": st.currency, "start": bal})
    _dbs[code] = c
    return c

def close_dbs():
    for c in _dbs.values(): c.close()
    _dbs.clear()

@contextlib.contextmanager
def rules(st):
    """Apply a strategy's config OVERRIDES while its code runs (desk/manual/run_variants.py:91-97)."""
    old = {k: getattr(C, k) for k in st.OVERRIDES}
    for k, v in st.OVERRIDES.items(): setattr(C, k, v)
    try: yield
    finally:
        for k, v in old.items(): setattr(C, k, v)

# ---- locks (exit 3 when busy)
def _lock(path, what, wait_s=0):
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
            if time.time() >= deadline:
                held = os.pread(fd, 300, 0).decode(errors="replace").strip(); os.close(fd)
                sys.stderr.write(f"stockdesk: {path} held ({held or 'unknown holder'}); refusing {what}\n"); sys.exit(3)
            time.sleep(0.5)
    os.ftruncate(fd, 0); os.pwrite(fd, f"pid={os.getpid()} {what} since {kst_str()}".encode(), 0)
    return fd

@contextlib.contextmanager
def cycle_lock(what, wait_s=0):
    fd = _lock(os.path.join(C.STATE, "cycle.lock"), what, wait_s)
    try: yield
    finally: os.ftruncate(fd, 0); fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)

# ---- book state / sizing / orders
def book_state(c, st, day):
    rows, mv, unreal = mark_value(c)
    eq = cash(c) + mv
    ok, why = R.can_enter(c, day)
    return {"currency": st.currency, "start": round(c.execute("SELECT start_balance FROM account WHERE id=1").fetchone()["start_balance"], 2),
            "equity": round(eq, 2), "cash": round(cash(c), 2), "freeCash": round(cash(c) - encumbered(c), 2),
            "openPositions": [{"code": r["code"], "name": r["name"], "qty": r["qty"], "entry": r["entry_price"], "last": r["last_price"], "holdDays": r["hold_days"]} for r in rows],
            "pendingBuys": c.execute("SELECT COUNT(*) n FROM orders WHERE status='PENDING' AND side='BUY'").fetchone()["n"],
            "canEnter": ok, "canEnterReason": why}

def _open_count(c):
    return len(open_positions(c)) + c.execute("SELECT COUNT(*) n FROM orders WHERE status='PENDING' AND side='BUY'").fetchone()["n"]

def place_entry(c, st, cand, run_id, slot, day, size_frac=None, signal=None, name=None):
    """Create a PENDING BUY order (or a SKIP record). Returns (status, value, reason)."""
    if c.execute("SELECT 1 FROM positions WHERE code=? AND status IN ('OPEN','HALTED')", (cand.code,)).fetchone() or \
       c.execute("SELECT 1 FROM orders WHERE code=? AND status='PENDING' AND side='BUY'", (cand.code,)).fetchone():
        return "SKIP", 0.0, "ALREADY_HELD"
    ok, why = R.can_enter(c, day)
    if not ok: return "SKIP", 0.0, why
    mo = st.max_open()
    if mo and _open_count(c) >= mo: return "SKIP", 0.0, "MAX_OPEN"
    eq = equity_now(c)
    value = eq * float(size_frac) if size_frac is not None else st.size(eq, cand)
    value = R.cap_entry_value(c, value)
    if value < F.min_order(st.market): return "ZERO", value, "BELOW_MIN_ORDER"
    kind, fill_at = st.order_kind(cand)
    limit_px = cand.screen_json.get("limit_px") if kind == "LIMIT" else None
    c.execute("INSERT INTO orders (ts,run_id,slot,candidate_id,market,code,name,side,kind,qty_req,value_req,limit_px,fill_at,expires_slot,status,reason,detail,signal_json) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (now(), run_id, slot, cand.id, st.market, cand.code, name or cand.name, "BUY", kind, None, value, limit_px, fill_at, fill_at, "PENDING", "", "",
               json.dumps(signal or cand.screen_json, ensure_ascii=False, default=str)))
    event(c, "SIZE", "ORDER", {"code": cand.code, "value": round(value, 2), "kind": kind, "fill_at": fill_at})
    return "PENDING", value, ""

def _ctx(st, slot, day, snap, regime_block, c):
    uni = SC.load_universe(M.mdb(), st.market)
    ban = SC.ban_set(M.mdb(), st.market, day)
    return Ctx(slot=slot, day=day, now=now(), market=st.market, snap=snap, universe=uni, ban=ban, regime_block=regime_block, lg=LOG,
               book_state=book_state(c, st, day))

# ---- prepare
def new_run_id(slot):
    base = f"stock-{slot}-{datetime.datetime.now(common.KST).strftime('%Y%m%d-%H%M%S')}"
    for n in range(1, 10):   # two prepares in the same second get -2, -3 ... (never reuse a run dir)
        rid = base if n == 1 else f"{base}-{n}"
        if not (os.path.exists(os.path.join(C.CYCLES_DIR, f"{rid}.json")) or os.path.exists(os.path.join(STORE, rid))): return rid
    sys.exit(f"run id {base} already exists")

def prepare(slot):
    if slot not in S.SLOTS: sys.exit(f"unknown slot {slot}")
    t0 = time.time(); day = S.slot_date(slot); run_id = new_run_id(slot)
    market = S.SLOTS[slot]["market"]
    books = strategies.for_slot(slot, "screen")
    held = {p["code"] for st in books for p in open_positions(vdb(st.code))}
    snap = SC.shared_snapshot(slot, day, market, held, LOG)
    regime_block, regime_rows = regime_context.build()
    jobs, out_books, pending_jobs = [], {}, []
    for st in books:
        c = vdb(st.code)
        with rules(st):
            ctx = _ctx(st, slot, day, snap, regime_block, c)
            try: cands = st.screen(ctx)
            except Exception as e:
                LOG.exception(f"{st.code} screen failed"); event(c, "SCREEN", "ERROR", str(e)); cands = []
        cands = [x for x in cands if x.code not in ctx.ban]          # bans are re-applied here; a strategy cannot lift them
        info = {"screened": len(cands), "jobs": 0, "orders": 0, "skips": []}
        for cand in cands:
            cur = c.execute("INSERT INTO candidates (ts,run_id,slot,market,code,name,score,screen_json,status) VALUES (?,?,?,?,?,?,?,?,?)",
                            (now(), run_id, slot, cand.market, cand.code, cand.name, cand.score, json.dumps(cand.screen_json, ensure_ascii=False, default=str),
                             "JUDGE_PENDING" if st.needs_llm else "CODE"))
            cand.id = cur.lastrowid
            if st.needs_llm:
                with rules(st): pending_jobs.append((st, cand, st.build_job(ctx, cand, run_id)))
            else:
                with rules(st): status, value, why = place_entry(c, st, cand, run_id, slot, day)
                c.execute("UPDATE candidates SET status=? WHERE id=?", (status, cand.id))
                if status == "PENDING": info["orders"] += 1
                else: info["skips"].append({"code": cand.code, "why": why})
        c.execute("INSERT INTO vcycles (run_id,slot,book,ts_prepare,screened,passed,buys,fills,closes,judged,note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, slot, st.code, now(), len(cands), len(cands), info["orders"], 0, 0, 0, ""))
        out_books[st.code] = info
    # round-robin job cap across books (desk/manual/run_variants.py:302-306)
    by_book = {}
    for st, cand, job in pending_jobs: by_book.setdefault(st.code, []).append((st, cand, job))
    over = []
    while any(by_book.values()):
        for code in list(by_book):
            if not by_book[code]: continue
            st, cand, job = by_book[code].pop(0)
            if len(jobs) < C.MAX_JOBS:
                jobs.append(job); out_books[code]["jobs"] += 1
                vdb(code).execute("UPDATE candidates SET judge_id=? WHERE id=?", (job["id"], cand.id))
            else:
                over.append({"book": code, "code": cand.code}); vdb(code).execute("UPDATE candidates SET status='OVER_JOB_CAP' WHERE id=?", (cand.id,))
    rundir = os.path.join(STORE, run_id)
    jobs_file = J.write_jobs(rundir, jobs) if jobs else None
    M.mark_slot(M.mdb(), slot, day, run_id, "prepare")
    cyc = {"runId": run_id, "slot": slot, "day": day, "market": market, "snapshot_source": snap.source, "books": out_books, "jobs": [j["id"] for j in jobs],
           "unjudged_over_cap": over, "max_jobs": C.MAX_JOBS, "routine_version": C.ROUTINE_VERSION, "regime_context": regime_block,
           "ts": now(), "kst": kst_str(), "timing_s": round(time.time() - t0, 2)}
    json.dump(cyc, open(os.path.join(C.CYCLES_DIR, f"{run_id}.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"runId": run_id, "slot": slot, "jobs": len(jobs), "jobsFile": jobs_file, "books": {k: {"screened": v["screened"], "jobs": v["jobs"], "orders": v["orders"]} for k, v in out_books.items()},
                      "unjudgedOverCap": len(over), "snapshot": snap.source, "timing_s": cyc["timing_s"]}, ensure_ascii=False))
    LOG.info(f"prepare {run_id} jobs={len(jobs)} books={out_books}")
    return cyc

# ---- finish
def finish(run_id, no_judge=False):
    p = os.path.join(C.CYCLES_DIR, f"{run_id}.json")
    if not os.path.exists(p): sys.exit(f"unknown run {run_id}")
    cyc = json.load(open(p)); slot, day = cyc["slot"], cyc["day"]
    for st in strategies.for_slot(slot, "screen"):
        if vdb(st.code).execute("SELECT ts_finish FROM vcycles WHERE run_id=?", (run_id,)).fetchone()["ts_finish"]:
            sys.exit(f"already finished {run_id}")
    results = None if no_judge else J.read_results(os.path.join(STORE, run_id))
    if not no_judge and cyc["jobs"] and results is None: sys.exit(f"results.jsonl missing for {run_id} (use --no-judge to finish without buys)")
    results = results or {}
    out = {}
    for st in strategies.for_slot(slot, "screen"):
        c = vdb(st.code); n_buy = n_judged = 0
        for cand_row in c.execute("SELECT * FROM candidates WHERE run_id=? AND status IN ('JUDGE_PENDING')", (run_id,)).fetchall():
            cand = strategies.Candidate(cand_row["market"], cand_row["code"], cand_row["name"] or "", cand_row["score"] or 0,
                                        json.loads(cand_row["screen_json"] or "{}"), id=cand_row["id"])
            res = results.get(cand_row["judge_id"]) if cand_row["judge_id"] else None
            j = res["json"] if res and res["ok"] else None
            with rules(st): decision, rule, ev = st.decide(j if not no_judge else None)
            if no_judge: rule = "NO_JUDGE"
            elif res is None: rule = "NO_JUDGE"
            elif not res["ok"] or j is None: rule = "JUDGE_UNPARSEABLE"
            else: n_judged += 1
            c.execute("INSERT INTO vjudge (run_id,candidate_id,market,code,job_id,claude_decision,confidence,p_win,payoff_ratio,ev,book_decision,rule,rationale,ts,model,effort) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (run_id, cand.id, cand.market, cand.code, cand_row["judge_id"], (j or {}).get("decision"), J._num((j or {}).get("confidence")),
                       J._num((j or {}).get("p_win")), J._num((j or {}).get("payoff_ratio")), ev, decision, rule, (j or {}).get("rationale"), now(),
                       res["model"] if res else None, res["effort"] if res else None))
            status = "SKIP"
            if decision == "BUY":
                targets = st.expand(cand, j, SC.load_universe(M.mdb(), st.market)) if hasattr(st, "expand") else [(cand.code, cand.name, None, cand.instrument, None)]
                for code, name, frac, instrument, signal in targets:
                    if code in SC.ban_set(M.mdb(), st.market, day): continue
                    sub = strategies.Candidate(cand.market, code, name, cand.score, signal or cand.screen_json, instrument, id=cand.id)
                    with rules(st): status, value, why = place_entry(c, st, sub, run_id, slot, day, size_frac=frac, signal=signal, name=name)
                    if status == "PENDING": n_buy += 1
            c.execute("UPDATE candidates SET status=? WHERE id=?", (status if decision == "BUY" else f"SKIP_{rule}", cand.id))
        c.execute("UPDATE vcycles SET ts_finish=?, buys=buys+?, judged=?, note=? WHERE run_id=?", (now(), n_buy, n_judged, "no-judge" if no_judge else "", run_id))
        out[st.code] = {"buys": n_buy, "judged": n_judged}
    M.mark_slot(M.mdb(), slot, day, run_id, "finish")
    res = {"runId": run_id, "slot": slot, "noJudge": no_judge, "books": out, "routine_version": C.ROUTINE_VERSION, "ts": now(), "kst": kst_str()}
    json.dump(res, open(os.path.join(C.CYCLES_DIR, f"{run_id}.result.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(res, ensure_ascii=False)); LOG.info(f"finish {run_id} {out}")
    return res

# ---- fill slots
def _fill_pending(c, st, snap, slot, day):
    n = 0
    for o in c.execute("SELECT * FROM orders WHERE status='PENDING' AND fill_at=?", (slot,)).fetchall():
        if kv_get(c, "halted", False):
            c.execute("UPDATE orders SET status='CANCELLED', reason='HALTED' WHERE id=?", (o["id"],)); continue
        code = o["code"]; inst = next((u.get("instrument") for u in SC.load_universe(M.mdb(), st.market) if u["code"] == code), "STOCK") or "STOCK"
        if o["kind"] == "CLOSE_AUCTION":
            r = snap.snap(code)
            f = F.fill_close_auction(st.market, o["value_req"], snap.mark(code), r["auction_turnover"] if r else None, r["turnover"] if r else None, inst)
        elif o["kind"] == "LIMIT":
            r = snap.snap(code)
            f = F.fill_limit(st.market, "BUY", o["value_req"], o["limit_px"], r["low"] if r else None, r["high"] if r else None, inst)
        else:
            f = F.fill_open(st.market, "BUY", o["value_req"], snap.open_price(code), snap.prev_turnover(code), inst)
        if f["status"] in ("NO_PRICE", "EXPIRED", "ZERO"):
            c.execute("UPDATE orders SET status=?, reason=?, detail=? WHERE id=?", (f["status"], f.get("detail", ""), "", o["id"]))
            event(c, "FILLS", f["status"], {"code": code, "kind": o["kind"]}); continue
        total = f["value"] + f["fee"] + f["tax"] + f["other"]
        c.execute("BEGIN IMMEDIATE")
        try:
            cur = c.execute("INSERT INTO positions (market,code,name,currency,strategy,instrument,qty,entry_price,entry_ts,entry_day,cost,peak_price,last_price,last_ts,last_day,status,signal_json,exit_slot) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (st.market, code, o["name"], st.currency, st.code, inst, f["qty"], f["price"], now(), day, total, f["price"], f["price"], now(), day, "OPEN",
                             o["signal_json"], (st.slots.get("exits") or [None])[0]))
            pid = cur.lastrowid
            c.execute("UPDATE account SET cash=cash-? WHERE id=1", (total,))
            c.execute("INSERT INTO fills (ts,order_id,position_id,action,market,code,qty,price,value,fee,tax,other_fee,partial,liquidity_ref,source,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (now(), o["id"], pid, "BUY", st.market, code, f["qty"], f["price"], f["value"], f["fee"], f["tax"], f["other"], f["partial"], f["liquidity_ref"], snap.source, f.get("detail", "")))
            c.execute("UPDATE orders SET status=?, position_id=? WHERE id=?", (f["status"], pid, o["id"]))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK"); raise
        event(c, "FILLS", "BUY", {"code": code, "qty": f["qty"], "px": f["price"], "value": round(f["value"], 2), "partial": f["partial"], "ref": f["liquidity_ref"]})
        st.on_fill(c, f); n += 1
    return n

def _exits(c, st, snap, slot, day):
    n = 0
    ctx = _ctx(st, slot, day, snap, "", c)
    is_open_slot = slot == S.NEXT_FILL_SLOT[st.market]
    for pos in open_positions(c):
        if pos["status"] == "HALTED": continue
        mark = snap.mark(pos["code"])
        with rules(st): rule = st.exits(pos, mark, ctx)
        if not rule: continue
        px = snap.open_price(pos["code"]) if is_open_slot else mark
        if px is None: continue
        if is_open_slot: px = px * (1 - C.OPEN_SLIP_BPS / 10_000)
        R.close_position(c, pos, px, rule, f"slot {slot}", "open" if is_open_slot else "mark", bot=st.code); n += 1
    return n

def equity_snapshot(c, st, day, kind, snap=None):
    rows, mv, unreal = mark_value(c)
    realized = c.execute("SELECT COALESCE(SUM(realized_pnl),0) s FROM positions WHERE status='CLOSED'").fetchone()["s"]
    eq = cash(c) + mv
    fx, fsrc, _ = M.fx_mark(M.mdb(), day)
    eq_krw = eq if st.currency == "KRW" else eq * fx
    if kind == "EOD": c.execute("DELETE FROM equity WHERE day=? AND kind='EOD'", (day,))
    c.execute("INSERT INTO equity (ts,day,kind,cash,equity,realized,unrealized,deployed,fx_rate,fx_source,equity_krw) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (now(), day, kind, cash(c), eq, realized, unreal, sum(r["cost"] or 0 for r in rows), fx if st.currency == "USD" else None, fsrc if st.currency == "USD" else None, eq_krw))
    return eq, eq_krw

def run_slot(slot):
    if slot not in S.SLOTS: sys.exit(f"unknown slot {slot}")
    t0 = time.time(); day = S.slot_date(slot); market = S.SLOTS[slot]["market"]
    books = [st for st in strategies.enabled() if st.market == market]
    held = {p["code"] for st in books for p in open_positions(vdb(st.code))}
    snap = SC.shared_snapshot(slot, day, market, held, LOG)
    flags = snap.all_flags(); kind = "EOD" if slot == S.EOD_SLOT[market] else "INTRA"
    out = {}
    for st in books:
        c = vdb(st.code)
        marks = {p["code"]: snap.mark(p["code"]) for p in open_positions(c)}
        r = R.risk_pass(c, st.code, marks, flags, day, lambda a, b: S.trading_days_between(market, a, b), LOG)
        filled = _fill_pending(c, st, snap, slot, day)      # orders carry their own fill_at; only those for this slot fill
        exits = _exits(c, st, snap, slot, day) if st in strategies.for_slot(slot, "exits") else 0
        eq, eq_krw = equity_snapshot(c, st, day, kind, snap)
        kv_set(c, f"slot_last:{slot}", {"day": day, "kst": kst_str()})
        out[st.code] = {"risk": r, "filled": filled, "exits": exits, "equity": round(eq, 2), "equity_krw": round(eq_krw, 0)}
    M.mark_slot(M.mdb(), slot, day, None, "slot")
    rec = {"slot": slot, "day": day, "kind": kind, "snapshot": snap.source, "books": out, "kst": kst_str(), "timing_s": round(time.time() - t0, 2)}
    with open(os.path.join(C.CYCLES_DIR, f"slots-{day.replace('-', '')}.jsonl"), "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False)); LOG.info(f"slot {slot} {out}")
    return rec

def due(run=False):
    ts = time.time()
    items = S.due(ts, lambda s, d: M.slot_done(M.mdb(), s, d), llm=False)
    if not run:
        print(json.dumps({"due": [{"slot": s, "day": d} for s, d in items]})); return items
    for s, d in items:
        with cycle_lock(f"slot {s}", wait_s=60): run_slot(s)
    if not items: print(json.dumps({"due": []}))
    return items

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "prepare" and len(a) == 2:
        with cycle_lock(f"prepare {a[1]}"): prepare(a[1])
    elif a[0] == "finish" and len(a) >= 2:
        with cycle_lock(f"finish {a[1]}", wait_s=120): finish(a[1], no_judge="--no-judge" in a)
    elif a[0] == "slot" and len(a) == 2:
        with cycle_lock(f"slot {a[1]}", wait_s=120): run_slot(a[1])
    elif a[0] == "due":
        due(run="--run" in a)
    else: sys.exit(__doc__)
