# Scratch test of independent books on a COPY of the desk. No network for holders, no real ledger writes.
import sys, json, os, glob, time, collections
os.environ["CLAUDE_CLI_MAX_JOBS"] = sys.argv[1] if len(sys.argv) > 1 else "40"
sys.path.insert(0, "/tmp/deskdry2"); sys.path.insert(0, "/tmp/deskdry2/manual")
import bots, common
CALLS = collections.Counter()
def f_rpc(mint, lg): CALLS[("rpc", mint)] += 1; return (10**9, [("acct", 10**7, "owner")], set(), "fake-rpc")   # 1% top holder
def f_hc(mint, lg): CALLS[("das", mint)] += 1; return (500, False, 1, "fake-das")
def f_pair(pair): CALLS[("pair", pair)] += 1; return ({"liquidity": {"usd": 10**9}}, None)
bots.top_holders_rpc, bots.holder_count_helius, bots.pair_by_address = f_rpc, f_hc, f_pair
import run_variants as rv
import book_rules as BR   # D no-chasing check: flat fake 1m candles, no GeckoTerminal call
BR.fetch_ohlcv_1m = lambda pool, lg=None, limit=40, t=None: ([[int(time.time()) - 60 * i, 1, 1.01, 0.99, 1, 10] for i in range(40)], "fake")
assert rv.DESK.startswith("/tmp/deskdry2"); rv.STORE = "/tmp/deskdry2_store"
base = rv.vdb("BASE")
rows = [dict(r) for r in base.execute("SELECT * FROM candidates WHERE symbol IN ('PIPER','NETWORK','FLOAT','VERSUS','PHONK') GROUP BY symbol")]
assert len(rows) >= 4, [r["symbol"] for r in rows]
toks = [r["token"] for r in rows]; pairs = {}
for r in rows:
    p = json.loads(r["data"]); p["liquidity"] = {"usd": 2_000_000}; p["priceChange"] = {"h1": 1}; p.setdefault("txns", {})
    p["txns"] = {"m5": {"buys": 10, "sells": 1}, "h1": {"buys": 50, "sells": 5}}; p["pairCreatedAt"] = (time.time() - 86400) * 1000
    pairs[r["token"]] = p
bots.scan_fetch = lambda lg: {"tokens": toks, "errs": [], "pairs": pairs, "perrs": []}
# make every book forget these tokens, then: BASE saw toks[0] 10 min ago; BASE holds toks[1]; C saw toks[2]
for v in rv.VARIANTS:
    c = rv.vdb(v); c.execute(f"UPDATE candidates SET ts=ts-7200 WHERE token IN ({','.join('?'*len(toks))}) AND ts>?", toks + [time.time() - 7200])
    c.execute("DELETE FROM positions WHERE status='OPEN'") if False else None
rv.vdb("BASE").execute("UPDATE candidates SET ts=? WHERE id=(SELECT MAX(id) FROM candidates WHERE token=?)", (time.time() - 600, toks[0]))
rv.vdb("C").execute("UPDATE candidates SET ts=? WHERE id=(SELECT MAX(id) FROM candidates WHERE token=?)", (time.time() - 600, toks[2]))
rv.vdb("BASE").execute("INSERT INTO positions (token,symbol,pair,status,entry_price,qty,cost_usd,last_price,opened_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                       (toks[1], "HELD", "pairX", "OPEN", 1.0, 1.0, 1.0, 1.0, time.time())) if "opened_ts" in [x[1] for x in rv.vdb("BASE").execute("PRAGMA table_info(positions)")] else None
rv.prepare()
cyc = json.load(open(sorted(glob.glob("/tmp/deskdry2/manual/variant_cycles/meme-var-*.json"))[-1]))
cands = {v: [r["token"] for r in cyc["variants"][v]] for v in rv.VARIANTS}
print("per-book candidates:", {v: len(x) for v, x in cands.items()})
assert toks[0] not in cands["BASE"] and all(toks[0] in cands[v] for v in "ABCD"), "BASE seen-recently leaked"
assert toks[2] not in cands["C"] and toks[2] in cands["BASE"], "C seen-recently leaked"
jobs = [json.loads(l) for l in open(glob.glob(f"/tmp/deskdry2_store/{cyc['run_id']}/jobs.jsonl")[0])]
passed = sum(1 for v in rv.VARIANTS for r in cyc["variants"][v] if r["vet_result"] != "REJECT")
print("passed total", passed, "jobs", len(jobs), "over cap", [(u["book"], u["symbol"]) for u in cyc["unjudged_over_cap"]])
assert len(jobs) == min(passed, rv.MAX_JOBS) and len(cyc["unjudged_over_cap"]) == passed - len(jobs)
assert all(j["id"] == f"{cyc['run_id']}:{j['book']}:{j['token']}" for j in jobs) and len({j["id"] for j in jobs}) == len(jobs)
assert all("Macro context" in j["user"] and f"Paper book {j['book']}" in j["user"] for j in jobs)
dj = [j for j in jobs if j["book"] == "D"]
if dj: print("D job book section:\n", dj[0]["user"].split("\n\nMarket data")[0][:1400])
dup = {k: n for k, n in CALLS.items() if n > 1}
print("raw holder/pair calls:", dict(collections.Counter(k[0] for k in CALLS.elements())), "unique mints", len(toks), "repeats", dup)
assert not dup, "holder lookups multiplied across books"
print("TEST OK", cyc["run_id"])
