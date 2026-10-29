import sqlite3, json, datetime, os
os.chdir("/workspace/desk")
L = "lost (collision)"
RID = "meme-var-20261029-0849"
KST = datetime.timezone(datetime.timedelta(hours=9))
def ep(s): return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST).timestamp()
s = json.load(open(f"manual/variant_cycles/{RID}.result.json"))
w0, w1 = ep("2026-10-29 08:49:13"), ep("2026-10-29 08:49:18")
b = sqlite3.connect("state/desk.db"); b.row_factory = sqlite3.Row
def row_for(c, tok):
    return c.execute("SELECT * FROM candidates WHERE token=? AND vet_ts BETWEEN ? AND ? ORDER BY id DESC LIMIT 1", (tok, w0, w1)).fetchone()
KEYS = ("id", "token", "symbol", "pair", "dex", "price", "liquidity", "fdv", "mcap", "pair_created", "score")
cands = []
for e in s["variants"]["BASE"]["vet"]:
    r = row_for(b, e["token"]); assert r, e["symbol"]
    p = json.loads(r["data"])
    extra = {"url": p.get("url"), "volume": p.get("volume"), "txns": p.get("txns"), "priceChange": p.get("priceChange")}
    cands.append({k: r[k] for k in KEYS} | extra)
drops = [dict(r) for r in b.execute("SELECT token,symbol,pair,reason FROM scan_drops WHERE ts BETWEEN ? AND ? ORDER BY id", (w0, w1))]
vars_, fin = {}, {}
for v, x in s["variants"].items():
    c = b if v == "BASE" else sqlite3.connect(f"state/variants/{v}.db"); c.row_factory = sqlite3.Row
    lst = []
    for e in x["vet"]:
        r = row_for(c, e["token"])
        bid = next(cc["id"] for cc in cands if cc["token"] == e["token"])
        lst.append({"cand": bid, "vid": r["id"] if r else L} | e)
    vars_[v] = lst
    eq = c.execute("SELECT ts FROM equity WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1", (w0, w1)).fetchone()
    tf = eq["ts"] if eq else ep("2026-10-29 08:49:17")
    fin[v] = (tf, "equity-row" if eq else "log-second")
    passed = sum(1 for e in x["vet"] if e["vet_result"] != "REJECT")
    buys = sum(1 for d in x["decisions"] if d["decision"] == "BUY")
    vals = (ep(s["scan_kst"][:19]), tf, len(x["vet"]), passed, buys, len(x["fills"]), len(x["risk"]), 0, s["judge"][:200], RID, v)
    c.execute("UPDATE vcycles SET ts_prepare=?,ts_finish=?,scanned=?,passed=?,buys=?,fills=?,closes=?,judged=?,note=? WHERE run_id=? AND variant=?", vals)
    c.commit()
out = {"run_id": RID, "scan_ts": L, "scan_kst": s["scan_kst"],
       "_reconstructed": "by repair0849.py from .result.json, ledger rows (08:49:13-18 KST window) and logs/variants.log; original overwritten by a manual prepare at 08:49:43 KST with the same minute runId",
       "scan_last": {"ts": L, "tokens": 58, "pairs": 53, "kept": 3, "errors": [], "_src": "logs/variants.log 08:49:14 KST"},
       "scan_drops": drops, "candidates": cands, "variants": vars_, "jobs": [], "unjudged_over_cap": [],
       "timing_s": {k: s["timing_s"][k] for k in ("scan", "vet_all_variants")}}
json.dump(out, open(f"manual/variant_cycles/{RID}.json", "w"), indent=1, default=str, ensure_ascii=False)
print("drops", len(drops), "cands", [c["symbol"] for c in cands], "fin", fin)
