"""End to end on the fake market: prepare (LLM + numeric books) -> fake results.jsonl (new format + a broken line) -> finish
-> fill slots -> exits -> EOD. Also: finish refuses a second run, --no-judge buys nothing, books stay independent.
Pattern: desk/manual/tests/test_judge_record.py."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done
import config as C
import run as RUN
import common

def write_results(run_id, answer_for):
    d = os.path.join(C.CLAUDE_CLI_STORE, run_id); rows = []
    for line in open(os.path.join(d, "jobs.jsonl")):
        j = json.loads(line)
        rows.append({"id": j["id"], "runId": run_id, "ok": True, "text": json.dumps(answer_for(j)), "claudeModel": "claude-fable-5-1",
                     "requestedModel": "fable", "requestedEffort": "medium", "durationMs": 900})
    with open(os.path.join(d, "results.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
        f.write("{not json\n")
    return len(rows)

def answer(j):
    if j["book"] == "TH":
        u = j["user"]; g = json.loads(u[u.index("screen data:\n") + 13:].split("\n\nMacro")[0])["top_gainers"]
        return {"decision": "BUY", "theme": "t", "leader": g[0]["code"], "second": g[1]["code"], "p_win": 0.6, "payoff_ratio": 2.0, "rationale": "x"}
    return {"decision": "BUY", "confidence": 0.7, "p_win": 0.6, "payoff_ratio": 2.0, "rationale": "x"}

# ---- CB: prepare -> finish -> close auction -> next open sell
cb = RUN.prepare("krx_cb"); rid = cb["runId"]
check("CB jobs written", len(cb["jobs"]) > 0 and os.path.exists(os.path.join(C.CLAUDE_CLI_STORE, rid, "jobs.jsonl")))
n = write_results(rid, answer)
res = RUN.finish(rid)
c = RUN.vdb("CB")
check("vjudge records model/effort from results", c.execute("SELECT COUNT(*) n FROM vjudge WHERE model='claude-fable-5-1' AND effort='medium'").fetchone()["n"] == n)
check(".result.json has routine_version key", "routine_version" in json.load(open(os.path.join(C.CYCLES_DIR, f"{rid}.result.json"))))
pend = c.execute("SELECT * FROM orders WHERE status='PENDING'").fetchall()
check("CB orders wait for the closing auction", pend and all(o["kind"] == "CLOSE_AUCTION" and o["fill_at"] == "krx_close" for o in pend))
try:
    RUN.finish(rid); check("second finish refused", False)
except SystemExit as e: check("second finish refused", "already finished" in str(e))

RUN.run_slot("krx_close")
filled = c.execute("SELECT COUNT(*) n FROM positions WHERE status='OPEN'").fetchone()["n"]
statuses = {r["status"] for r in c.execute("SELECT status FROM orders")}
check("closing auction processed every CB order", "PENDING" not in statuses, statuses)
check("EOD equity row written at krx_close", c.execute("SELECT COUNT(*) n FROM equity WHERE kind='EOD'").fetchone()["n"] == 1)
RUN.run_slot("krx_open")
check("CB sells everything at the next open", c.execute("SELECT COUNT(*) n FROM positions WHERE status='OPEN'").fetchone()["n"] == 0)
if filled:
    r = c.execute("SELECT * FROM positions WHERE status='CLOSED'").fetchone()
    check("CB close rule + tax charged", r["close_rule"] == "CB_SELL_NEXT_OPEN" and c.execute("SELECT SUM(tax) t FROM fills WHERE action='SELL'").fetchone()["t"] > 0)
    acct = c.execute("SELECT cash FROM account").fetchone()["cash"]
    check("cash = start + realized (no open positions)", abs(acct - (C.START_BALANCE_KRW + sum(x["realized_pnl"] for x in c.execute("SELECT realized_pnl FROM positions")))) < 0.01)

# ---- krx_after: numeric books order immediately, LLM books after finish
af = RUN.prepare("krx_after"); rid2 = af["runId"]
fl = RUN.vdb("FL")
check("FL (numeric) placed orders at prepare", fl.execute("SELECT COUNT(*) n FROM orders WHERE run_id=?", (rid2,)).fetchone()["n"] > 0)
check("DT has no orders before finish", RUN.vdb("DT").execute("SELECT COUNT(*) n FROM orders WHERE run_id=?", (rid2,)).fetchone()["n"] == 0)
write_results(rid2, answer); RUN.finish(rid2)
th = RUN.vdb("TH")
th_orders = th.execute("SELECT * FROM orders WHERE run_id=?", (rid2,)).fetchall()
check("TH expands one judgment into leader + second", len(th_orders) == 2 and {json.loads(o["signal_json"])["role"] for o in th_orders} == {"leader", "second"})
check("TH leader sized bigger than second", sorted(o["value_req"] for o in th_orders)[1] > sorted(o["value_req"] for o in th_orders)[0])
check("DT bought after an EV>0 judgment", RUN.vdb("DT").execute("SELECT COUNT(*) n FROM orders WHERE run_id=?", (rid2,)).fetchone()["n"] == 1)
check("independent books: CB ledger untouched by krx_after", c.execute("SELECT COUNT(*) n FROM orders WHERE run_id=?", (rid2,)).fetchone()["n"] == 0)

# ---- --no-judge: nothing bought for LLM books
cb2 = RUN.prepare("krx_cb"); RUN.finish(cb2["runId"], no_judge=True)
check("--no-judge -> no CB orders", c.execute("SELECT COUNT(*) n FROM orders WHERE run_id=?", (cb2["runId"],)).fetchone()["n"] == 0)
check("--no-judge recorded as NO_JUDGE", c.execute("SELECT COUNT(*) n FROM vjudge WHERE run_id=? AND rule='NO_JUDGE'", (cb2["runId"],)).fetchone()["n"] == len(cb2["jobs"]))

# ---- missing results.jsonl refused unless --no-judge
af2 = RUN.prepare("krx_after")
if af2["jobs"]:
    try: RUN.finish(af2["runId"]); check("missing results refused", False)
    except SystemExit as e: check("missing results refused", "results.jsonl missing" in str(e))

# ---- RISK flags: a held 관리종목 is sold at the next fill slot before strategy exits
import marketdb as M, screen as SC
fl_pos = fl.execute("SELECT code FROM orders WHERE run_id=? AND status='PENDING'", (rid2,)).fetchall()
RUN.run_slot("krx_open")
held = [p["code"] for p in common.open_positions(fl)]
if held:
    M.put_flags(M.mdb(), "KRX", RUN.S.slot_date("krx_open"), {held[0]: ["관리종목"]}, "test")
    RUN.run_slot("krx_open")
    r = fl.execute("SELECT close_rule FROM positions WHERE code=? ORDER BY id DESC", (held[0],)).fetchone()
    check("RISK closes a 관리종목 position", r["close_rule"].startswith("FLAG_"), r["close_rule"])
done()
