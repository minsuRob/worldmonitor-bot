import sys, time, json; sys.path.insert(0, "/workspace/desk/manual")
import regime_context as R
now = 1793232000.0
def boom(k): raise RuntimeError("down")
b, rows = R.build(now=now, getter=boom)
assert all(r["status"] == "missing" for r in rows) and b.count(": unavailable") == 6, b
fake = {"market:crypto:v1": {"_seed": {"fetchedAt": (now - 3600) * 1000}, "data": {"quotes": [{"symbol": "BTC", "price": 1.0, "change": 2.0}]}},
        "economic:fred:v1:VIXCLS:0": {"series": {"observations": [{"date": "d1", "value": 1}, {"date": "d2", "value": None}]}},
        "seed-meta:economic:fred:v1:VIXCLS:0": {"fetchedAt": (now - 7 * 3600) * 1000},
        "claude-cli:v1:latest:insights:insights": {"text": "x " * 400, "finishedAt": "2026-10-29T00:00:00Z"}}
b, rows = R.build(now=now, getter=fake.get)
st = {r["label"]: r["status"] for r in rows}
assert st == {"BTC": "ok", "SOL": "missing", "VIX (FRED)": "stale", "Risk mood (F&G)": "missing", "WTI (EIA)": "missing", "WM insight": "ok"}, st
assert len(b) <= 600 and "WM insight: x x" in b and "..." in b, b
print(b); print("ALL REGIME TESTS PASS", len(b))
