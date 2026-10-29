"""Fake-data tests for the 2026-10-29 book redesign (B = old C, C = momentum rider, D = early sniper).
Runs on a throw-away COPY of the desk code (fresh state dir), no network, no real ledgers.
  python3 manual/tests/test_books_v2.py"""
import sys, os, shutil, tempfile, json, time
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="books_v2_")
for f in os.listdir(SRC):
    if f.endswith(".py"): shutil.copy(os.path.join(SRC, f), TMP)
shutil.copytree(os.path.join(SRC, "manual"), os.path.join(TMP, "manual"), ignore=shutil.ignore_patterns("variant_cycles", "*.json", "__pycache__", "tests"))
sys.path.insert(0, TMP); sys.path.insert(0, os.path.join(TMP, "manual"))
os.environ.pop("HELIUS_API_KEY", None)
import config as C
assert C.STATE.startswith(TMP)
C.HELIUS_RPC = None
import bots, common
TOP = {}       # mint -> largest holder fraction
HOLDERS = {}   # mint -> holder count
def f_rpc(mint, lg): return (1e9, [("acct", TOP.get(mint, 0.01) * 1e9, "owner")], set(), "fake-rpc")
def f_hc(mint, lg): return (HOLDERS[mint], False, 1, "fake-das") if mint in HOLDERS else None
def f_pair(pair): return ({"liquidity": {"usd": 1e9}, "priceUsd": "1"}, None)
bots.top_holders_rpc, bots.holder_count_helius, bots.pair_by_address = f_rpc, f_hc, f_pair
bots.top_holders_rugcheck = lambda m, lg: None
import run_variants as RV, book_rules as BR
lg = common.logger("test_books_v2")
OK = []
def check(name, cond, info=""):
    assert cond, f"FAIL {name} {info}"; OK.append(name)

T = time.time()
def pair(h1=0, h6=0, m5=0, b5=20, s5=10, vm5=1000, vh1=6000, age_min=120, liq=50_000):
    return {"priceChange": {"m5": m5, "h1": h1, "h6": h6}, "txns": {"m5": {"buys": b5, "sells": s5}, "h1": {"buys": 100, "sells": 80}},
            "volume": {"m5": vm5, "h1": vh1, "h24": 50_000, "h6": 20_000}, "liquidity": {"usd": liq}, "pairCreatedAt": (T - age_min * 60) * 1000}
def pc(p): return p["pairCreatedAt"] / 1000

# ---------- 1. numeric prechecks
for v in ("BASE", "A", "B"):
    check(f"precheck {v} none", BR.precheck(v, pair(h1=-50, m5=-40), None, T) is None)
p = pair(h1=40, h6=60, m5=2, b5=30, s5=20); check("C momentum pass", BR.precheck("C", p, pc(p), T) is None)
p = pair(h1=5, h6=60, m5=2); check("C h1<10 reject", BR.precheck("C", p, pc(p), T)[0] == "C_no_momentum")
p = pair(h1=40, h6=-5, m5=2); check("C h6<0 reject", BR.precheck("C", p, pc(p), T)[0] == "C_no_momentum")
p = pair(h1=40, h6=60, m5=-12); check("C m5 collapse reject", BR.precheck("C", p, pc(p), T)[0] == "C_collapsing")
p = pair(h1=40, h6=60, m5=1, b5=10, s5=15); check("C sell pressure reject", BR.precheck("C", p, pc(p), T)[0] == "C_sell_pressure")
p = pair(age_min=60, b5=40, s5=20, vm5=1500, vh1=6000); check("D signal pass", BR.precheck("D", p, pc(p), T) is None)
p = pair(age_min=3, b5=40, s5=20, vm5=1500, vh1=6000); check("D too young", BR.precheck("D", p, pc(p), T)[0] == "D_age")
p = pair(age_min=25 * 60, b5=40, s5=20, vm5=1500, vh1=6000); check("D too old", BR.precheck("D", p, pc(p), T)[0] == "D_age")
check("D age unknown", BR.precheck("D", pair(), None, T)[0] == "D_age")
p = pair(age_min=60, b5=24, s5=20, vm5=1500, vh1=6000); check("D buy ratio 1.2 reject", BR.precheck("D", p, pc(p), T)[0] == "D_buy_ratio")
p = pair(age_min=60, b5=8, s5=1, vm5=1500, vh1=6000); check("D inactive reject", BR.precheck("D", p, pc(p), T)[0] == "D_inactive")
p = pair(age_min=60, b5=40, s5=20, vm5=500, vh1=6000); check("D no accel reject (1.0x)", BR.precheck("D", p, pc(p), T)[0] == "D_no_accel")
p = pair(age_min=60, m5=-20, b5=40, s5=20, vm5=1500, vh1=6000); check("D collapsing reject", BR.precheck("D", p, pc(p), T)[0] == "D_collapsing")
check("D postcheck few holders", BR.postcheck("D", 30)[0] == "D_few_holders")
check("D postcheck ok / unknown", BR.postcheck("D", 80) is None and BR.postcheck("D", None) is None)

# ---------- 2. vet_one thresholds per book (top holder, h1 limit, min liquidity)
def cand_row(c, mint, p):
    c.execute("""INSERT INTO candidates (ts,token,symbol,pair,dex,liquidity,fdv,mcap,price,pair_created,score,data,status)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (T, mint, mint[:6], "pair_" + mint, "x", p["liquidity"]["usd"], 1e6, 1e6, 1.0, pc(p), 1.0, json.dumps(p), "NEW"))
    return c.execute("SELECT * FROM candidates WHERE id=last_insert_rowid()").fetchone()
def vet(v, mint, p, top=0.01):
    TOP[mint] = top; c = RV.vdb(v)
    with RV.rules(v): return bots.vet_one(c, cand_row(c, mint, p), lg)
r = vet("BASE", "m_top7", pair(), 0.07); check("BASE top 7% reject", r[0] == "REJECT" and r[1] == "1_top_holder")
r = vet("B", "m_top7b", pair(), 0.07); check("B top 7% pass (8% limit = old C)", r[0] != "REJECT", r)
r = vet("C", "m_top9", pair(h1=40), 0.09); check("C top 9% reject", r[1] == "1_top_holder")
r = vet("D", "m_top9d", pair(), 0.09); check("D top 9% pass (10%)", r[0] != "REJECT", r)
r = vet("D", "m_top11", pair(), 0.11); check("D top 11% reject", r[1] == "1_top_holder")
r = vet("BASE", "m_h1_40", pair(h1=40)); check("BASE h1 40 reject", r[1] == "4_already_in_h1")
r = vet("C", "m_h1_120", pair(h1=120)); check("C h1 120 pass", r[0] != "REJECT", r)
r = vet("C", "m_h1_160", pair(h1=160)); check("C h1 160 reject", r[1] == "4_already_in_h1")
r = vet("D", "m_h1_250", pair(h1=250)); check("D h1 250 pass", r[0] != "REJECT", r)
r = vet("D", "m_h1_320", pair(h1=320)); check("D h1 320 reject", r[1] == "4_already_in_h1")
r = vet("D", "m_liq6k", pair(liq=6_000)); check("D liq 6k pass", r[0] != "REJECT", r)
r = vet("C", "m_liq6k_c", pair(liq=6_000)); check("C liq 6k reject", r[1] == "2_liquidity")

# ---------- 3. sizing
def order(v, liq):
    c = RV.vdb(v)
    with RV.rules(v): return bots.planned_meme_order(c, liq)
d, kr, kc, why = order("BASE", 200_000); check("BASE size 6% cap = $60", abs(d - 60) < 1e-6 and abs(kc - 0.06) < 1e-9, d)
d, *_ = order("A", 200_000); check("A size $60", abs(d - 60) < 1e-6)
d, *_ = order("B", 200_000); check("B size $60", abs(d - 60) < 1e-6)
d, *_ = order("C", 200_000); check("C size 10% = $100", abs(d - 100) < 1e-6, d)
d, *_ = order("C", 10_000); check("C size slip-capped $50 at 10k liq", abs(d - 50) < 1e-6, d)
d, *_ = order("D", 200_000); check("D size 5% = $50", abs(d - 50) < 1e-6, d)
d, *_ = order("D", 5_000); check("D $50 fits at 5k liq (4% budget)", abs(d - 50) < 1e-6, d)
check("config restored", C.SIZE_FIXED_FRACTION is None and C.MAX_OPEN_POSITIONS is None and C.KELLY_CAP == 0.06)
# max open positions: D with 10 open -> ZERO
cD = RV.vdb("D")
for i in range(10):
    cD.execute("INSERT INTO positions (kind,token,symbol,pair,status,entry_price,qty,cost_usd,last_price,peak_price,opened_ts,entry_liq) VALUES ('meme',?,?,?,'OPEN',1,10,10,1,1,?,50000)",
               (f"held{i}", f"H{i}", f"ph{i}", T))
row = cand_row(cD, "m_maxopen", pair())
cD.execute("UPDATE candidates SET status='VETTED', vet_result='PASS' WHERE id=?", (row["id"],))
with RV.rules("D"): bots.size_tick(cD, lg)
o = cD.execute("SELECT * FROM orders WHERE candidate_id=?", (row["id"],)).fetchone()
check("D max 10 open -> ZERO", o["status"] == "ZERO" and "max open" in o["reason"], dict(o))
cD.execute("DELETE FROM positions"); cD.execute("DELETE FROM orders")
row = cand_row(cD, "m_open_ok", pair())
cD.execute("UPDATE candidates SET status='VETTED', vet_result='PASS' WHERE id=?", (row["id"],))
with RV.rules("D"): bots.size_tick(cD, lg)
o = cD.execute("SELECT * FROM orders WHERE candidate_id=?", (row["id"],)).fetchone()
check("D sized $50 when room", o["status"] == "SIZED" and abs(o["dollars"] - 50) < 1e-6, dict(o))
cD.execute("DELETE FROM orders")

# ---------- 4. buy rules
good = {"decision": "SKIP", "p_win": 0.5, "payoff_ratio": 2.0}; bad = {"decision": "BUY", "p_win": 0.3, "payoff_ratio": 1.2}
check("BASE follows word", BR.decide("BASE", good)[0] == "SKIP" and BR.decide("BASE", bad)[0] == "BUY")
check("B follows word", BR.decide("B", bad)[0] == "BUY")
check("A EV", BR.decide("A", good)[0] == "BUY" and BR.decide("A", bad)[0] == "SKIP")
check("C EV", BR.decide("C", good)[0] == "BUY" and BR.decide("C", bad)[0] == "SKIP")
e = BR.decide("C", {"p_win": 0.40, "payoff_ratio": 1.6})   # 0.64-0.6-0.03 = +0.01
check("C EV edge +0.01 buys", e[0] == "BUY" and abs(e[2] - 0.01) < 1e-9, e)
check("D veto", BR.decide("D", {"decision": "SKIP", "p_win": .9, "payoff_ratio": 9})[0] == "SKIP"
      and BR.decide("D", {"decision": "BUY", "p_win": .1, "payoff_ratio": .5})[0] == "BUY")
check("D no answer -> SKIP", BR.decide("D", None)[0] == "SKIP")

# ---------- 5. exits (stop, partial TP, trailing) with the shared close model
def mkpos(c, sym, last, peak, entry=1.0, qty=100.0, cost=100.0):
    c.execute("INSERT INTO positions (kind,token,symbol,pair,status,entry_price,qty,cost_usd,last_price,peak_price,opened_ts,entry_liq) VALUES ('meme',?,?,?,'OPEN',?,?,?,?,?,?,1e9)",
              ("t_" + sym, sym, "p_" + sym, entry, qty, cost, last, peak, T))
    return c.execute("SELECT id FROM positions WHERE symbol=?", (sym,)).fetchone()["id"]
def setpx(c, pid, last, peak): c.execute("UPDATE positions SET last_price=?, peak_price=MAX(peak_price,?) WHERE id=?", (last, peak, pid))
def pos(c, pid): return c.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
cC = RV.vdb("C"); cash0 = common.cash(cC)
pid = mkpos(cC, "CSTOP", 0.81, 1.0); BR.book_exits(cC, "C", lg, bots.close_position); check("C -19% holds", pos(cC, pid)["status"] == "OPEN")
setpx(cC, pid, 0.79, 1.0); BR.book_exits(cC, "C", lg, bots.close_position)
p_ = pos(cC, pid); check("C -21% stop", p_["status"] == "CLOSED" and p_["close_rule"] == "C_STOP_-20%", dict(p_))
pid = mkpos(cC, "CTP", 1.9, 1.9); BR.book_exits(cC, "C", lg, bots.close_position); check("C 1.9x no TP", pos(cC, pid)["qty"] == 100)
setpx(cC, pid, 2.05, 2.05); BR.book_exits(cC, "C", lg, bots.close_position); p_ = pos(cC, pid)
check("C 2x partial 50%", p_["status"] == "OPEN" and abs(p_["qty"] - 50) < 1e-9 and abs(p_["cost_usd"] - 50) < 1e-9, dict(p_))
pf = cC.execute("SELECT * FROM fills WHERE position_id=? AND action='SELL_PARTIAL'", (pid,)).fetchone()
exp_proc = 50 * 2.05 - common.fee_for(50 * 2.05)   # liq 1e9 -> ~no impact
check("C partial proceeds", abs(pf["filled_usd"] - exp_proc) < 0.01, pf["filled_usd"])
setpx(cC, pid, 2.6, 3.0); BR.book_exits(cC, "C", lg, bots.close_position); check("C no 2nd TP, 2.6 > 3.0*0.75", pos(cC, pid)["status"] == "OPEN" and abs(pos(cC, pid)["qty"] - 50) < 1e-9)
setpx(cC, pid, 2.2, 3.0); BR.book_exits(cC, "C", lg, bots.close_position); p_ = pos(cC, pid)
exp_total = exp_proc + (50 * 2.2 - common.fee_for(50 * 2.2))
check("C trail close after TP", p_["status"] == "CLOSED" and p_["close_rule"].startswith("C_TRAIL_-25%"), dict(p_))
check("C realized includes partial", abs(p_["realized_pnl"] - (exp_total - 100)) < 0.02 and abs(p_["cost_usd"] - 100) < 1e-9, (p_["realized_pnl"], exp_total - 100))
cDx = RV.vdb("D")
pid = mkpos(cDx, "DSTOP", 0.66, 1.0); BR.book_exits(cDx, "D", lg, bots.close_position); check("D -34% holds", pos(cDx, pid)["status"] == "OPEN")
setpx(cDx, pid, 0.64, 1.0); BR.book_exits(cDx, "D", lg, bots.close_position); check("D -36% stop", pos(cDx, pid)["close_rule"] == "D_STOP_-35%")
pid = mkpos(cDx, "DTP", 2.9, 2.9); BR.book_exits(cDx, "D", lg, bots.close_position); check("D 2.9x no TP", pos(cDx, pid)["qty"] == 100)
setpx(cDx, pid, 3.1, 3.1); BR.book_exits(cDx, "D", lg, bots.close_position); check("D 3x partial", abs(pos(cDx, pid)["qty"] - 50) < 1e-9)
setpx(cDx, pid, 3.0, 5.0); BR.book_exits(cDx, "D", lg, bots.close_position); check("D 40% trail holds at -40.0% edge", pos(cDx, pid)["status"] == "CLOSED")  # 3.0 <= 5*0.6
for v in ("BASE", "A", "B"):
    cx = RV.vdb(v); pidx = mkpos(cx, "NOEXIT" + v, 0.1, 9.0)
    check(f"{v} has no book exits", BR.book_exits(cx, v, lg, bots.close_position) == [] and pos(cx, pidx)["status"] == "OPEN")

# ---------- 6. prompts: BASE/A unchanged wording, D gets the veto system prompt
txt = {}
for v in RV.VARIANTS:
    with RV.rules(v): txt[v] = RV.book_rules_text(v)
check("BASE text", txt["BASE"].startswith("Baseline book.") and "Buy rule: the book buys if you answer BUY." in txt["BASE"])
check("A text", txt["A"].endswith("using your numbers, so calibrate them."))
check("B text", txt["B"].startswith("Differs from BASE: largest-holder limit 8%"))
check("C text", "MOMENTUM RIDER" in txt["C"] and "stop-loss at -20%" in txt["C"] and "fixed 10%" in txt["C"])
check("D text", "EARLY SNIPER" in txt["D"] and "VETO only" in txt["D"] and "stop-loss at -35%" in txt["D"])
check("D system prompt", "RUG VETO" in BR.D_SYSTEM and '"decision":"BUY"|"SKIP"' in BR.D_SYSTEM)
print(f"ALL {len(OK)} CHECKS OK  (tmp copy {TMP})")
shutil.rmtree(TMP, ignore_errors=True)
