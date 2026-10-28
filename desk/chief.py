"""CHIEF: supervisor only. Never opens, sizes, or closes positions. Never overrides RISK."""
import subprocess, sys, json, time, os, signal
import config as C
from common import *

PY = sys.executable
lg = logger("supervisor")

def first_line(j):
    s = json.dumps(j, ensure_ascii=False) if j is not None else ""
    return s[:160]

def run_checks(c):
    res = {}
    for name, path in C.WM_CHECKS.items():
        st, j, lat, err = http_json(C.WM_BASE + path, timeout=15)
        ok = False; why = err or ""
        if st == 200 and isinstance(j, dict):
            if name == "fear_greed":
                ok = not j.get("unavailable") and j.get("compositeScore") is not None
                why = "" if ok else "unavailable:true / no compositeScore"
            elif name == "prediction_markets":
                ok = bool(j.get("dataAvailable")) and bool(j.get("markets")) and bool(j.get("fetchedAt"))
                why = "" if ok else "dataAvailable false or no markets"
            else:
                ok = bool(j.get("signals"))
                why = "" if ok else "no signals"
        res[name] = {"ok": ok, "http": st, "latency_ms": round(lat, 1), "why": why, "first": first_line(j)}
        c.execute("INSERT INTO checks (ts,name,ok,http,latency_ms,first_line,detail) VALUES (?,?,?,?,?,?,?)",
                  (now(), name, int(ok), st, lat, first_line(j), why))
    st, j, lat, err = http_json(f"{C.DEX}/latest/dex/search?q=BONK")
    ok = st == 200 and isinstance(j, dict) and "pairs" in j and bool(j["pairs"])
    res["dexscreener_bonk"] = {"ok": ok, "http": st, "latency_ms": round(lat, 1), "why": "" if ok else (err or "no pairs")}
    c.execute("INSERT INTO checks (ts,name,ok,http,latency_ms,first_line,detail) VALUES (?,?,?,?,?,?,?)",
              (now(), "dexscreener_bonk", int(ok), st, lat, "", res["dexscreener_bonk"]["why"]))
    wm_ok = all(res[k]["ok"] for k in C.WM_CHECKS)
    prev = kv_get(c, "degraded", None)
    kv_set(c, "degraded", not wm_ok)
    if prev is not None and prev != (not wm_ok):
        lg.info(f"degraded -> {not wm_ok}")
    kv_set(c, "checks", res)
    return res

class Sup:
    def __init__(self, c):
        self.c = c; self.procs = {}; self.miss = {b: 0 for b in C.BOTS}; self.deaths = {b: [] for b in C.BOTS}

    def spawn(self, b):
        out = open(os.path.join(C.LOGS, f"{b}.out"), "a")
        p = subprocess.Popen([PY, os.path.join(C.BASE, "bots.py"), b], cwd=C.BASE, stdout=out, stderr=out, start_new_session=True)
        self.procs[b] = p
        self.c.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?,?)", (b, p.pid, now(), "spawned", ""))
        lg.info(f"spawn {b} pid={p.pid}")

    def kill(self, b):
        p = self.procs.get(b)
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(10)
            except Exception: p.kill()

    def halt(self, b):
        kv_set(self.c, "halted", True)
        kv_set(self.c, "halt_reason", f"{b} died {C.DEATHS_PER_HOUR_HALT}x within 1h at {kst_str()}")
        lg.error(f"HALT: {b} died {C.DEATHS_PER_HOUR_HALT} times within 1h. Entry bots stopped. No positions closed. RISK left running.")
        event(self.c, "chief", "HALT", kv_get(self.c, "halt_reason"))
        for x in C.BOTS:
            if x != "risk": self.kill(x)

    def supervise(self):
        hl = halted(self.c)
        for b in C.BOTS:
            if hl and b != "risk": continue
            p = self.procs.get(b)
            h = self.c.execute("SELECT * FROM health WHERE bot=?", (b,)).fetchone()
            dead = p is None or p.poll() is not None
            stale = h is None or now() - h["last_hb"] > C.HEARTBEAT_STALE_S
            if dead or stale:
                self.miss[b] += 1
                lg.warning(f"{b} missed response #{self.miss[b]} (dead={dead}, hb_age={now()-h['last_hb'] if h else None})")
                if self.miss[b] >= 2:
                    self.deaths[b] = [t for t in self.deaths[b] if now() - t < 3600] + [now()]
                    if len(self.deaths[b]) >= C.DEATHS_PER_HOUR_HALT and not halted(self.c):
                        self.halt(b)
                        if b != "risk": return   # RISK is kept alive even when halted
                    if True:
                        self.kill(b); self.spawn(b); self.miss[b] = 0
                        lg.warning(f"restarted {b} once after 2 missed responses")
                        event(self.c, "chief", "RESTART", b)
            else:
                self.miss[b] = 0

def write_summary(c):
    a = c.execute("SELECT * FROM account WHERE id=1").fetchone()
    rows, mv, unreal = mark_positions(c)
    realized = c.execute("SELECT COALESCE(SUM(realized_pnl),0) s FROM positions WHERE status='CLOSED'").fetchone()["s"]
    deployed = c.execute("SELECT COALESCE(SUM(cost_usd),0) s FROM positions").fetchone()["s"]
    equity = a["cash"] + mv
    total = realized + unreal
    health = {}
    for h in c.execute("SELECT * FROM health"):
        health[h["bot"]] = {"pid": h["pid"], "status": h["status"], "hb_age_s": round(now() - h["last_hb"], 1), "detail": h["detail"]}
    checks = kv_get(c, "checks", {})
    wm_ok = all((checks.get(k) or {}).get("ok") for k in C.WM_CHECKS)
    dex_ok = (checks.get("dexscreener_bonk") or {}).get("ok", False)
    bots_ok = all(health.get(b, {}).get("hb_age_s", 1e9) <= C.HEARTBEAT_STALE_S for b in C.BOTS)
    ds = day_start_ts()
    rejects_today = c.execute("SELECT COUNT(*) n FROM candidates WHERE vet_result='REJECT' AND vet_ts>=?", (ds,)).fetchone()["n"]
    c.execute("INSERT INTO equity (ts,cash,equity,realized,unrealized,deployed) VALUES (?,?,?,?,?,?)", (now(), a["cash"], equity, realized, unreal, deployed))
    s = {
        "updated": kst_str(), "paper_only": True,
        "start_balance": a["start_balance"], "cash": round(a["cash"], 4), "equity": round(equity, 4),
        "realized_pnl": round(realized, 4), "unrealized_pnl": round(unreal, 4), "total_pnl": round(total, 4),
        "deployed_capital": round(deployed, 4),
        "pnl_pct_of_deployed": round(total / deployed * 100, 4) if deployed else None,
        "open_positions": [{"id": r["id"], "kind": r["kind"], "symbol": r["symbol"], "side": r["side"], "qty": r["qty"],
                            "cost_usd": r["cost_usd"], "entry_price": r["entry_price"], "last_price": r["last_price"],
                            "value_usd": (r["qty"] or 0) * (r["last_price"] or r["entry_price"] or 0),
                            "pnl_usd": (r["qty"] or 0) * (r["last_price"] or r["entry_price"] or 0) - (r["cost_usd"] or 0)} for r in rows],
        "last_alert_snapshot": json.load(open(C.ALERT_SNAPSHOT)) if os.path.exists(C.ALERT_SNAPSHOT) else None,
        "bot_health": health,
        "checks": checks,
        "degraded": not wm_ok,
        "degraded_reason": "; ".join(f"{k}: http {v.get('http')} {v.get('why')}" for k, v in checks.items() if k in C.WM_CHECKS and not v.get("ok")) or None,
        "halted": halted(c), "halt_reason": kv_get(c, "halt_reason"),
        "READY": bool(wm_ok and dex_ok and bots_ok and not halted(c)),
        "vet_rejects_today": rejects_today,
        "vet_reject_flag": rejects_today < C.VET_MIN_REJECTS_PER_DAY,
    }
    tmp = C.SUMMARY + ".tmp"
    json.dump(s, open(tmp, "w"), ensure_ascii=False, indent=2); os.replace(tmp, C.SUMMARY)
    return s

def main():
    c = init_db()
    open(os.path.join(C.STATE, "chief.pid"), "w").write(str(os.getpid()))
    lg.info(f"CHIEF start pid={os.getpid()} WM_BASE={C.WM_BASE}")
    stop = {"v": False}
    def onterm(*_): stop["v"] = True
    signal.signal(signal.SIGTERM, onterm); signal.signal(signal.SIGINT, onterm)
    sup = Sup(c)
    for b in C.BOTS: sup.spawn(b)
    last_sup = last_chk = 0
    last_ready = None
    while not stop["v"]:
        try:
            if now() - last_chk >= C.CHECKS_EVERY_S:
                last_chk = now(); run_checks(c); s = write_summary(c)
                if s["READY"] != last_ready:
                    lg.info(f"READY={s['READY']} degraded={s['degraded']} reason={s['degraded_reason']}"); last_ready = s["READY"]
            if now() - last_sup >= C.SUPERVISE_EVERY_S:
                last_sup = now(); sup.supervise()
            k = kst()
            day = kst_day()
            if k.hour >= C.CLOSE_REPORT_HOUR and kv_get(c, "last_close_report") != day:
                out = os.path.join(C.REPORTS, f"close_{day}.txt")
                r = subprocess.run([PY, os.path.join(C.BASE, "report.py")], capture_output=True, text=True, cwd=C.BASE)
                open(out, "w").write(r.stdout + (r.stderr and "\n[stderr]\n" + r.stderr))
                kv_set(c, "last_close_report", day); lg.info(f"close report written {out}")
        except Exception as e:
            lg.error(f"chief loop error {type(e).__name__}: {e}")
        time.sleep(2)
    lg.info("CHIEF stopping: terminating bots (positions are NOT closed)")
    for b in C.BOTS: sup.kill(b)

if __name__ == "__main__":
    main()
