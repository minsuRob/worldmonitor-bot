"""Every registered strategy honours the plugin contract; the registry rejects bad plugins; RISK/ban sit outside plugins."""
import os, sys, json, importlib, textwrap
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done, DESK
import config as C
import strategies
import schedule as S
import marketdb as M
import screen as SC
import risk as R
import run as RUN
import gen_rules_doc as G
from strategies.base import Strategy, Candidate, Ctx

REG = strategies.REGISTRY
check("8 strategies registered", set(REG) == {"CB", "DT", "FL", "EV", "MO", "TH", "MO-US", "ER-US"}, set(REG))
check("template not registered", "XX" not in REG)
check("deterministic order (file-name sorted)", list(REG) == sorted(REG, key=lambda c: c.lower().replace("-", "_")))

# ---- registry validation rejects bad plugins (write temp modules, import a fresh copy of the package)
def try_plugin(name, body):
    p = os.path.join(DESK, "strategies", f"{name}.py")
    open(p, "w").write(textwrap.dedent(body))
    try:
        importlib.invalidate_caches()
        return strategies.discover(), None
    except ValueError as e:
        return None, str(e)
    finally:
        os.remove(p); sys.modules.pop(f"strategies.{name}", None)

_, err = try_plugin("zz", """
from .base import Strategy
class ZZ(Strategy):
    code, name, market = "ZZ", "bad", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    OVERRIDES = {"MAX_POSITION_PCT": 0.9}
    def screen(self, ctx): return []
""")
check("OVERRIDES on RISK key rejected", err and "RISK key" in err, err)
_, err = try_plugin("zy", """
import risk
from .base import Strategy
class ZY(Strategy):
    code, name, market = "ZY", "bad", "KRX"
    def screen(self, ctx): return []
""")
check("import risk rejected", err and "must not import risk" in err, err)
_, err = try_plugin("zx", """
from .base import Strategy
class WRONG(Strategy):
    code, name, market = "NOPE", "bad", "KRX"
    def screen(self, ctx): return []
""")
check("code != module name rejected", err and "must equal module name" in err, err)
_, err = try_plugin("zw", """
from .base import Strategy
class ZW(Strategy):
    code, name, market = "ZW", "bad", "KRX"
    slots = {"screen": "krx_open", "fill_entry": "krx_open", "exits": ()}
    needs_llm = True; buy_mode = "ev"; system_prompt = "x"
    def screen(self, ctx): return []
""")
check("LLM strategy in a non-LLM slot rejected", err and "no LLM leg" in err, err)
_, err = try_plugin("zv", """
from .base import Strategy
class ZV(Strategy):
    code, name, market = "ZV", "bad", "US"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ()}
    def screen(self, ctx): return []
""")
check("market/slot mismatch rejected", err and "not a US slot" in err, err)
reg2, err = try_plugin("zu", """
from .base import Strategy
class ZU(Strategy):
    code, name, market = "ZU", "good", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    PARAMS = {"size_frac": 0.1, "stop": 0.05}
    def screen(self, ctx): return []
""")
check("valid extra plugin registers", err is None and "ZU" in reg2, err)

# ---- per-strategy contract on the fake market
day = "2026-10-30"   # a Friday: momentum books rebalance
c = M.mdb()
for st in REG.values():
    slot = st.slots["screen"]
    snap = SC.shared_snapshot(slot, day, st.market)
    ledger = RUN.vdb(st.code)
    ctx = Ctx(slot=slot, day=day, now=0.0, market=st.market, snap=snap, universe=SC.load_universe(c, st.market), ban=SC.ban_set(c, st.market, day),
              regime_block="Macro context: test", book_state=RUN.book_state(ledger, st, day))
    with RUN.rules(st): cands = st.screen(ctx)
    check(f"{st.code}: screen returns Candidates", isinstance(cands, list) and all(isinstance(x, Candidate) for x in cands), cands[:1])
    check(f"{st.code}: candidates are in its market", all(x.market == st.market for x in cands))
    d_ko, d_en = st.describe("ko"), st.describe("en")
    check(f"{st.code}: describe keys == rules table columns", set(d_ko) == set(G.COLUMNS) == set(d_en) and d_ko["screen"], (set(d_ko), d_ko.get("screen")))
    for k in st.OVERRIDES: check(f"{st.code}: override {k} not RISK", k not in R.PROTECTED_KEYS)
    src = open(os.path.join(DESK, "strategies", st.code.lower().replace("-", "_") + ".py"), encoding="utf-8").read()
    check(f"{st.code}: module does not import risk", "import risk" not in src and "from risk" not in src)
    if st.needs_llm:
        cand = cands[0] if cands else Candidate(st.market, "000001", "x", 1.0, {"k": 1})
        job = st.build_job(ctx, cand, "stock-test-1")
        for f in ("id", "runId", "pipeline", "stage", "book", "promptHash", "system", "user", "maxTokens", "responseFormat"):
            check(f"{st.code}: job has {f}", f in job and job[f] not in (None, ""), f)
        check(f"{st.code}: job pipeline stock / book code", job["pipeline"] == "stock" and job["book"] == st.code and job["id"].startswith("stock-test-1:" + st.code + ":"))
        check(f"{st.code}: user prompt carries book state and macro", "Paper book" in job["user"] and "Macro context: test" in job["user"])
        d = st.decide({"decision": "BUY", "p_win": 0.6, "payoff_ratio": 2.0})
        check(f"{st.code}: decide BUY json -> tuple", d[0] in ("BUY", "SKIP") and isinstance(d[1], str) and d[2] is not None, d)
        check(f"{st.code}: decide None -> SKIP (fail closed)", st.decide(None)[0] == "SKIP")
    else:
        check(f"{st.code}: numeric decide -> BUY/CODE", st.decide(None) == ("BUY", "CODE", None))
    # size never exceeds the strategy fraction; RISK caps it again
    eq = 1_000_000.0
    with RUN.rules(st): v = st.size(eq, cands[0] if cands else Candidate(st.market, "X"))
    check(f"{st.code}: size <= equity", 0 < v <= eq)
    check(f"{st.code}: RISK cap <= MAX_POSITION_PCT", R.cap_entry_value(ledger, 10 * eq) <= C.MAX_POSITION_PCT * RUN.equity_now(ledger) + 1e-6)
    # exits on a fake position
    pos = {"id": 0, "code": "000001", "market": st.market, "entry_price": 100.0, "peak_price": 130.0, "hold_days": 999, "signal_json": "{}", "qty": 1, "status": "OPEN"}
    with RUN.rules(st): r_stop = st.exits(pos, 50.0, ctx); r_none = st.exits({**pos, "hold_days": 0, "peak_price": 100.0}, 100.0, ctx)
    check(f"{st.code}: exits returns str|None", (r_stop is None or isinstance(r_stop, str)) and (r_none is None or isinstance(r_none, str)), (r_stop, r_none))
    if st.p("stop"): check(f"{st.code}: deep loss -> stop rule", r_stop and "STOP" in r_stop, r_stop)
    if st.code == "CB": check("CB always exits next open", r_none == "CB_SELL_NEXT_OPEN")

# ---- bans are re-applied by run.py even if a strategy returns a banned code
class Leaky(Strategy):
    code, name, market = "LEAK", "leaky", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    def screen(self, ctx): return [Candidate("KRX", code, "b") for code in sorted(ctx.ban)][:1]
leak = Leaky()
strategies.REGISTRY["LEAK"] = leak
try:
    out = RUN.prepare("krx_after")
    lc = RUN.vdb("LEAK")
    check("banned candidate never becomes an order or candidate row", lc.execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"] == 0
          and lc.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 0 and out["books"]["LEAK"]["screened"] == 0, out["books"].get("LEAK"))
finally:
    del strategies.REGISTRY["LEAK"]

# ---- RISK runs before strategy exits and can_enter blocks entries
b = RUN.vdb("FL"); import common
common.kv_set(b, "halted", True)
check("halted -> can_enter False", R.can_enter(b, day) == (False, "HALTED"))
st = REG["FL"]; status, v, why = RUN.place_entry(b, st, Candidate("KRX", "999999", "x", 1, {}), "r", "krx_after", day)
check("halted book places no order", status == "SKIP" and why == "HALTED", (status, why))
common.kv_set(b, "halted", False)
done()
