# Scratch dry run: full prepare() on a COPY of the desk, forced 1 candidate, jobs to /tmp. No real ledger/store writes.
import sys, json, os, glob
sys.path.insert(0, "/tmp/deskdry"); sys.path.insert(0, "/tmp/deskdry/manual")
import run_variants as rv, bots
assert rv.DESK.startswith("/tmp/deskdry"), rv.DESK
rv.STORE = "/tmp/deskdry_store"
def fake_scan(base, lg):
    r = dict(base.execute("SELECT * FROM candidates WHERE symbol='FLOAT' ORDER BY id DESC LIMIT 1").fetchone())
    r.pop("id"); r["status"] = "NEW"
    base.execute(f"INSERT INTO candidates ({','.join(r)}) VALUES ({','.join('?'*len(r))})", list(r.values())); base.commit()
bots.scan_once = fake_scan
bots.vet_one = lambda c, row, lg: ("PASS", None, "dry-run forced pass")
bots.check_top_holder = lambda d, lg: (True, "largest holder >5%: dry-run")
bots.holder_count_helius = lambda tok, lg: None
try: rv.prepare()
except SystemExit as e: print("exit", e)
jf = glob.glob("/tmp/deskdry_store/*/jobs.jsonl")[0]
jobs = [json.loads(l) for l in open(jf)]
u = jobs[0]["user"]; blk = u.split("\n\n", 1)[1]
print("jobs:", len(jobs)); print(blk); print("block chars:", len(blk))
cyc = json.load(open(glob.glob("/tmp/deskdry/manual/variant_cycles/meme-var-*%s.json" % jobs[0]["runId"][-6:])[0]))
assert cyc["regime_context"]["block"] == blk and len(blk) < 600
print("cycle record has regime_context rows:", [(r["label"], r["status"]) for r in cyc["regime_context"]["rows"]])
