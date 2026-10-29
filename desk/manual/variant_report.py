"""Paper variant comparison. Every number is read from the ledgers (state/desk.db = BASE, state/variants/<V>.db).
Usage: python3 manual/variant_report.py [--json]"""
import sys, os, json, glob
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import run_variants as RV
from common import kst_str

def stats(v):
    c = RV.vdb(v)
    acct = c.execute("SELECT * FROM account WHERE id=1").fetchone()
    cyc = c.execute("SELECT COUNT(*) n, MIN(ts_prepare) a, SUM(CASE WHEN ts_finish IS NOT NULL THEN 1 ELSE 0 END) f, "
                    "COALESCE(SUM(passed),0) p, COALESCE(SUM(buys),0) b FROM vcycles").fetchone()
    opens = c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
    closed = c.execute("SELECT * FROM positions WHERE status='CLOSED'").fetchall()
    mv = sum((r["qty"] or 0) * (r["last_price"] or r["entry_price"] or 0) for r in opens)
    unreal = mv - sum(r["cost_usd"] or 0 for r in opens)
    realized = sum(r["realized_pnl"] or 0 for r in closed)
    wins = sum(1 for r in closed if (r["realized_pnl"] or 0) > 0)
    fills_buy = c.execute("SELECT COUNT(*) n FROM fills WHERE action='BUY'").fetchone()["n"]
    since = cyc["a"] or 0
    eq = [r["equity"] for r in c.execute("SELECT equity FROM equity WHERE ts>=? ORDER BY ts", (since,))]
    peak, mdd = acct["start_balance"], 0.0
    for e in [acct["start_balance"]] + eq:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak else 0)
    out = {"variant": v, "cycles": cyc["n"], "cycles_finished": cyc["f"], "candidates_passed_vet": cyc["p"], "buys": cyc["b"],
           "buy_fills": fills_buy, "open_positions": len(opens), "closed_positions": len(closed),
           "realized_pnl_usd": round(realized, 2), "unrealized_pnl_usd": round(unreal, 2),
           "cash_usd": round(acct["cash"], 2), "equity_usd": round(acct["cash"] + mv, 2),
           "win_rate": (round(wins / len(closed), 3) if closed else None), "max_drawdown_pct": round(mdd * 100, 2),
           "first_cycle": kst_str(cyc["a"]) if cyc["a"] else None}
    # judged decisions per judge model/effort (NULL = recorded before 2026-10-29 or not reported -> "unknown")
    out["judge_models"] = {f"{r['m'] or 'unknown'}/{r['e'] or 'unknown'}": r["n"] for r in c.execute(
        "SELECT model m, effort e, COUNT(*) n FROM vjudge WHERE job_id IS NOT NULL GROUP BY model, effort ORDER BY n DESC")}
    if v == "BASE":
        out["legacy_manual_cycles_before_runner"] = len(glob.glob(os.path.join(HERE, "meme-cli-*.scanvet.json")))
    return out

if __name__ == "__main__":
    rows = [stats(v) for v in RV.VARIANTS]
    if "--json" in sys.argv: print(json.dumps(rows, indent=1)); sys.exit()
    print(f"Paper variant report  {kst_str()}  (equity = cash + qty*last RISK mark; no exit costs in unrealized)")
    hdr = ["variant", "cycles", "passed", "buys", "open", "closed", "realized$", "unreal$", "equity$", "winrate", "maxDD%"]
    print("  ".join(f"{h:>9}" for h in hdr))
    for r in rows:
        vals = [r["variant"], r["cycles"], r["candidates_passed_vet"], r["buys"], r["open_positions"], r["closed_positions"],
                f"{r['realized_pnl_usd']:.2f}", f"{r['unrealized_pnl_usd']:.2f}", f"{r['equity_usd']:.2f}",
                "-" if r["win_rate"] is None else f"{r['win_rate']*100:.0f}%", f"{r['max_drawdown_pct']:.2f}"]
        print("  ".join(f"{str(x):>9}" for x in vals))
    print("judge model/effort (judged decisions):")
    for r in rows:
        print(f"  {r['variant']:>4}: " + (", ".join(f"{k} {n}" for k, n in r["judge_models"].items()) or "-"))
    b = rows[0]
    print(f"BASE also had {b['legacy_manual_cycles_before_runner']} manual cycles before the variant runner (all SKIP, no fills).")
    print("A=EV rule (p*b-(1-p)-3%>0)  B=top holder 8% (old C)  C=aggressive momentum rider  D=aggressive early sniper (Claude veto)  | shared RISK identical; C/D add own exits")
