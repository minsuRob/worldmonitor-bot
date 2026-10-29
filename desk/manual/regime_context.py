"""Compact macro/market regime block for the memecoin judge prompt (PAPER ONLY, read-only).

Reads the local World Monitor Redis (Upstash-style REST, creds from env or /workspace/worldmonitor/.env.local).
Every value carries its own timestamp; anything missing or older than MAX_AGE_H is printed as 'unavailable'.
Never raises: on any error the block says so. Does not touch variant rules, VET, SIZE or RISK.
"""
import os, json, time, datetime, urllib.request

WM_ENV = "/workspace/worldmonitor/.env.local"
MAX_AGE_H = 6.0
MAX_CHARS = 600
KST = datetime.timezone(datetime.timedelta(hours=9))


def _creds():
    url, tok = os.environ.get("UPSTASH_REDIS_REST_URL"), os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if (not url or not tok) and os.path.exists(WM_ENV):
        for line in open(WM_ENV):
            k, _, v = line.strip().partition("=")
            v = v.strip().strip('"').strip("'")
            if k == "UPSTASH_REDIS_REST_URL" and not url: url = v
            if k == "UPSTASH_REDIS_REST_TOKEN" and not tok: tok = v
    return url, tok


def _get(key, url, tok):
    req = urllib.request.Request(url, data=json.dumps(["GET", key]).encode(),
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    raw = json.loads(urllib.request.urlopen(req, timeout=5).read()).get("result")
    return json.loads(raw) if raw else None


def _ts(v):
    """epoch ms/s or ISO string -> epoch seconds"""
    if v is None: return None
    if isinstance(v, (int, float)): return v / 1000 if v > 1e11 else float(v)
    return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()


def _kst(ts): return datetime.datetime.fromtimestamp(ts, KST).strftime("%m-%d %H:%M KST")


def _crypto(g):
    d = g("market:crypto:v1")
    ts = _ts(d["_seed"]["fetchedAt"]); out = []
    q = {x["symbol"]: x for x in d["data"]["quotes"]}
    for sym in ("BTC", "SOL"):
        x = q.get(sym)
        out.append((sym, f"${x['price']:,.2f} {x['change']:+.2f}% 24h" if x else None, ts))
    return out


def _vix(g):
    s = g("economic:fred:v1:VIXCLS:0")["series"]["observations"]
    obs = [o for o in s if o.get("value") is not None][-1]
    meta = g("seed-meta:economic:fred:v1:VIXCLS:0") or {}
    return [("VIX (FRED)", f"{obs['value']} close {obs['date']}", _ts(meta.get("fetchedAt")))]


def _mood(g):
    d = g("market:fear-greed:v1")
    c = d["data"]["composite"]
    return [("Risk mood (F&G)", f"{c['score']} {c['label']}", _ts(d["_seed"]["fetchedAt"]))]


def _wti(g):
    d = g("energy:eia-petroleum:v1")
    w = d["data"]["wti"]
    return [("WTI (EIA)", f"${w['current']}/bbl wk {w['date']}", _ts(d["_seed"]["fetchedAt"]))]


def _headline(g):
    d = g("claude-cli:v1:latest:insights:insights")
    txt = " ".join((d.get("text") or "").split())
    if len(txt) > 150: txt = txt[:147].rsplit(" ", 1)[0] + "..."
    return [("WM insight", txt or None, _ts(d.get("finishedAt") or d.get("importedAt")))]


ITEMS = [("BTC/SOL", _crypto), ("VIX (FRED)", _vix), ("Risk mood (F&G)", _mood), ("WTI (EIA)", _wti), ("WM insight", _headline)]


def build(now=None, getter=None):
    """Return (block_text, details_list). details: [{label, value, ts, age_h, status}]"""
    now = now or time.time()
    if getter is None:
        url, tok = _creds()
        if not url or not tok:
            return "Macro context: unavailable (World Monitor Redis not configured)", []
        getter = lambda k: _get(k, url, tok)
    rows = []
    for label, fn in ITEMS:
        try:
            got = fn(getter)
        except Exception:
            got = [("BTC", None, None), ("SOL", None, None)] if fn is _crypto else [(label, None, None)]
        for lab, val, ts in got:
            age = (now - ts) / 3600 if ts else None
            if val is None or ts is None: st = "missing"
            elif age > MAX_AGE_H: st = "stale"
            else: st = "ok"
            rows.append({"label": lab, "value": val, "ts": ts, "age_h": round(age, 2) if age is not None else None, "status": st})
    lines = [f"Macro context (World Monitor, {_kst(now)}; >{MAX_AGE_H:g}h old = unavailable; background only):"]
    for r in rows:
        if r["status"] == "ok": lines.append(f"{r['label']}: {r['value']} [{_kst(r['ts'])}]")
        elif r["status"] == "stale": lines.append(f"{r['label']}: unavailable (stale {r['age_h']:.1f}h)")
        else: lines.append(f"{r['label']}: unavailable")
    block = "\n".join(lines)
    while len(block) > MAX_CHARS and len(lines) > 1:   # trim the headline first, then drop trailing lines
        if lines[-1].startswith("WM insight") and len(lines[-1]) > 60:
            lines[-1] = lines[-1][:max(60, len(lines[-1]) - (len(block) - MAX_CHARS) - 3)] + "..."
        else:
            lines.pop()
        block = "\n".join(lines)
    return block, rows


if __name__ == "__main__":
    b, rows = build()
    print(b); print(f"[{len(b)} chars]")
    for r in rows: print(r["label"], r["status"], r["age_h"])
