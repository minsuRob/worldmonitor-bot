"""Build Claude-CLI judge jobs for VET-passed candidates of a run (same format as meme-cli-20261029-0126)."""
import sys, json, os, hashlib, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import *
import bots
run_id = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
sv = json.load(open(os.path.join(here, f"{run_id}.scanvet.json")))
tmpl = json.loads(open("/workspace/worldmonitor/data/claude-cli/meme-cli-20261029-0126/jobs.jsonl").readline())
SYSTEM = tmpl["system"]
c = init_db(); lg = logger("manual")
outdir = f"/workspace/worldmonitor/data/claude-cli/{run_id}"; os.makedirs(outdir, exist_ok=True)
n = 0
with open(os.path.join(outdir, "jobs.jsonl"), "w") as f:
    for cand in sv["candidates"]:
        if cand["vet_result"] not in ("PASS", "PASS_PARTIAL") or n >= 10: continue
        row = c.execute("SELECT * FROM candidates WHERE id=?", (cand["id"],)).fetchone()
        ok, hdet = bots.check_top_holder(row, lg)
        order, *_ = bots.planned_meme_order(c, cand["liquidity"])
        v = cand["volume"] or {}
        data = {"symbol": cand["symbol"], "mint": cand["token"], "pair": cand["pair"], "dex": cand["dex"],
                "priceUsd": cand["price"], "liquidityUsd": cand["liquidity"], "fdvUsd": cand["fdv"], "marketCapUsd": cand["mcap"],
                "pairAgeHours": round((sv["scan_ts"] - cand["pair_created"]) / 3600, 2) if cand["pair_created"] else None,
                "volumeUsd": {k: v.get(k) for k in ("h24", "h6", "h1", "m5")},
                "txns": cand["txns"], "priceChangePct": cand["priceChange"],
                "holderConcentration": hdet, "holderCount": "unknown (DexScreener gives none)",
                "scanMomentumScore": cand["score"],
                "vet": f"{cand['vet_result']}: {cand['vet_detail']}",
                "plannedPaperOrderUsd": round(order, 2), "accountEquityUsd": round(bots.equity_now(c), 2)}
        user = f"Market data snapshot (DexScreener, {sv['scan_kst']}):\n" + json.dumps(data, indent=1)
        n += 1
        job = {"id": f"{run_id}-{n:03d}", "runId": run_id, "pipeline": "memecoin", "stage": "judge",
               "promptHash": hashlib.sha256((SYSTEM + "\0" + user).encode()).hexdigest()[:16],
               "openrouterModel": None, "openrouterCacheKey": None, "maxTokens": 400, "responseFormat": "json_object",
               "system": SYSTEM, "user": user, "capturedAt": datetime.datetime.utcnow().isoformat() + "Z",
               "candidateId": cand["id"], "token": cand["token"], "symbol": cand["symbol"]}
        f.write(json.dumps(job) + "\n")
print("jobs", n, outdir)
