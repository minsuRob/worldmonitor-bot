"""Manual ONE-cycle SCAN+VET (paper only), using the desk's own functions unchanged."""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as C
from common import *
import bots
run_id = sys.argv[1]
c = init_db(); lg = logger("manual")
t0 = now()
before = c.execute("SELECT COALESCE(MAX(id),0) m FROM candidates").fetchone()["m"]
dbefore = c.execute("SELECT COALESCE(MAX(id),0) m FROM scan_drops").fetchone()["m"]
bots.scan_once(c, lg)
print("scan_last", kv_get(c, "scan_last"))
drops = [dict(r) for r in c.execute("SELECT token,symbol,pair,reason FROM scan_drops WHERE id>?", (dbefore,))]
cands = c.execute("SELECT * FROM candidates WHERE id>? ORDER BY score DESC", (before,)).fetchall()
out = {"run_id": run_id, "scan_ts": t0, "scan_kst": kst_str(t0), "scan_last": kv_get(c, "scan_last"), "scan_drops": drops, "candidates": []}
for cand in cands:
    try: res, chk, det = bots.vet_one(c, cand, lg)
    except Exception as e: res, chk, det = "REJECT", "error", f"{type(e).__name__}: {e}"
    c.execute("UPDATE candidates SET status=?, vet_result=?, vet_check=?, vet_detail=?, vet_ts=? WHERE id=?",
              ("VETTED" if res != "REJECT" else "REJECTED", res, chk, det, now(), cand["id"]))
    lg.info(f"[{run_id}] vet {cand['symbol']} {res} {chk or ''} {det}")
    p = json.loads(cand["data"])
    out["candidates"].append({"id": cand["id"], "token": cand["token"], "symbol": cand["symbol"], "pair": cand["pair"],
        "url": p.get("url"), "dex": cand["dex"], "price": cand["price"], "liquidity": cand["liquidity"], "fdv": cand["fdv"],
        "mcap": cand["mcap"], "pair_created": cand["pair_created"], "score": cand["score"],
        "volume": p.get("volume"), "txns": p.get("txns"), "priceChange": p.get("priceChange"),
        "vet_result": res, "vet_check": chk, "vet_detail": det})
    print(cand["symbol"], res, chk, det)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{run_id}.scanvet.json"), "w"), indent=1, default=str)
print("done", kst_str())
