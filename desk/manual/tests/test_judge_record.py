"""Fake-data tests for recording the judge model/effort (vjudge.model/effort, .result.json, report) and the routine version.
Runs on a throw-away COPY of the desk code (fresh state dir), no network, no real ledgers, no node, no claude.
  python3 manual/tests/test_judge_record.py"""
import sys, os, shutil, tempfile, json, sqlite3, subprocess, types
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="judge_record_")
for f in os.listdir(SRC):
    if f.endswith(".py"): shutil.copy(os.path.join(SRC, f), TMP)
shutil.copytree(os.path.join(SRC, "manual"), os.path.join(TMP, "manual"), ignore=shutil.ignore_patterns("variant_cycles", "*.json", "__pycache__", "tests"))
sys.path.insert(0, TMP); sys.path.insert(0, os.path.join(TMP, "manual"))
os.environ.pop("HELIUS_API_KEY", None)
os.environ["DESK_ROUTINE_VERSION"] = "test-1"
import config as C
assert C.STATE.startswith(TMP)
C.HELIUS_RPC = None
import bots
bots.risk_measure = lambda p: ({"liquidity": {"usd": 1e9}, "priceUsd": "1"}, None)
import run_variants as RV, variant_report as VR
OK = []
def check(name, cond, info=""):
    assert cond, f"FAIL {name} {info}"; OK.append(name)

# ---------- 1. an existing ledger without the new columns gets them; old rows are kept as NULL
old = os.path.join(RV.VDIR, "A.db")
c0 = sqlite3.connect(old)
c0.executescript(RV.EXTRA)
c0.execute("INSERT INTO vjudge (run_id, job_id, claude_decision, variant_decision, rule, ts) VALUES ('old-run','old-job','BUY','BUY','EV>0',1)")
c0.commit(); c0.close()
c = RV.vdb("A")
cols = {r[1] for r in c.execute("PRAGMA table_info(vjudge)")}
check("migration adds model/effort", {"model", "effort"} <= cols, cols)
r = c.execute("SELECT model, effort, claude_decision FROM vjudge WHERE run_id='old-run'").fetchone()
check("old row kept, model/effort NULL", r["claude_decision"] == "BUY" and r["model"] is None and r["effort"] is None, dict(r))
RV.vdb("A")   # second open: no duplicate ALTER
check("migration idempotent", True)

# ---------- 2. runner_requested: runner /2 lines carry requested values, /1 lines -> None
rundir = tempfile.mkdtemp(prefix="run_", dir=TMP)
with open(os.path.join(rundir, "results.jsonl"), "w") as f:
    f.write(json.dumps({"id": "new", "claudeModel": "m-real", "requestedModel": "m-req", "requestedEffort": "high"}) + "\n\n")
    f.write(json.dumps({"id": "old", "claudeModel": "m-real"}) + "\n")
req = RV.runner_requested(rundir)
check("requested from runner /2", req["new"] == ("m-req", "high"), req)
check("runner /1 line -> None", req["old"] == (None, None), req)
check("no results.jsonl -> empty", RV.runner_requested(os.path.join(TMP, "missing")) == {})

# ---------- 3. finish end to end: vjudge row and .result.json carry model/effort and routine version
RUN = "meme-var-20990101-000000"
RV.STORE = os.path.join(TMP, "claude-cli"); rd = os.path.join(RV.STORE, RUN); os.makedirs(rd)
MINT = "FakeMint1111111111111111111111111111111111"
cid = c.execute("""INSERT INTO candidates (ts,token,symbol,pair,dex,liquidity,fdv,mcap,price,pair_created,score,data,status)
                   VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?)""", (MINT, "FAKE", "pairF", "x", 1e5, 1e6, 1e6, 1.0, 1.0, 1.0, "{}", "NEW")).lastrowid
job_id = f"{RUN}:A:{MINT}"
vet_row = {"cand": cid, "vid": cid, "token": MINT, "symbol": "FAKE", "score": 1.0, "vet_result": "PASS", "vet_check": None,
           "vet_detail": None, "planned_order": 60.0, "order_reason": None, "kelly_capped": 0.06}
cyc = {"run_id": RUN, "scan_kst": "test", "routine_version": "test-1", "jobs": [{"id": job_id, "book": "A", "token": MINT, "symbol": "FAKE"}],
       "candidates": [{"token": MINT, "symbol": "FAKE"}], "variants": {v: ([vet_row] if v == "A" else []) for v in RV.VARIANTS}}
json.dump(cyc, open(os.path.join(RV.CYCLES_DIR, f"{RUN}.json"), "w"))
for v in RV.VARIANTS:
    RV.vdb(v).execute("INSERT INTO vcycles (run_id, variant, ts_prepare) VALUES (?,?,1)", (RUN, v))
with open(os.path.join(rd, "results.jsonl"), "w") as f:
    f.write(json.dumps({"id": job_id, "claudeModel": "m-real", "requestedModel": None, "requestedEffort": "medium"}) + "\n")
judge = {"decision": "SKIP", "confidence": 0.5, "p_win": 0.1, "payoff_ratio": 1.0, "rationale": "fake"}
def fake_run(args, cwd=None, **kw):   # stands in for import-results.mjs: writes stored.jsonl
    with open(os.path.join(rd, "stored.jsonl"), "w") as f:
        f.write(json.dumps({"jobId": job_id, "ok": True, "parsedJson": judge, "durationMs": 5, "claudeModel": "m-real", "apiKeySource": "none"}) + "\n")
    return types.SimpleNamespace(returncode=0, stdout="imported 1\n", stderr="")
RV.subprocess.run = fake_run
RV.finish(RUN)
row = RV.vdb("A").execute("SELECT model, effort, variant_decision FROM vjudge WHERE run_id=?", (RUN,)).fetchone()
check("vjudge model = CLI-reported model", row["model"] == "m-real", dict(row))
check("vjudge effort = requested effort", row["effort"] == "medium", dict(row))
res = json.load(open(os.path.join(RV.CYCLES_DIR, f"{RUN}.result.json")))
cl = res["claude"]["A"][MINT]
check("result.json model/effort", cl["model"] == "m-real" and cl["effort"] == "medium" and cl["requested_model"] is None, cl)
check("result.json routine version", res["routine_version"] == {"prepare": "test-1", "finish": "test-1"}, res["routine_version"])

# ---------- 4. report groups judged decisions by model/effort (NULL -> unknown)
jm = VR.stats("A")["judge_models"]
check("report judge_models", jm == {"m-real/medium": 1, "unknown/unknown": 1}, jm)

print(f"ALL {len(OK)} CHECKS OK  (tmp copy {TMP})")
