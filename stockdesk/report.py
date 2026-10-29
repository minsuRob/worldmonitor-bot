"""Per-book report and return-trajectory series. Every number comes from the book ledgers (state/books/<CODE>.db).

  python3 report.py [--json]                              per-book table (currency return, KRW return, FX effect, MDD, fees/taxes, judge models)
  python3 report.py --series daily|weekly [--since D] [--json|--csv path]   KRW-normalized return series, one column per book, + MDD
출처 패턴: desk/manual/variant_report.py (stats, MDD loop).
"""
import sys, os, json, csv
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import config as C
import run as RUN
import strategies
import marketdb as M
import gen_rules_doc
from common import kst_str, kv_get

def _mdd(series, start):
    peak, mdd, peak_day = start, 0.0, None
    for day, e in series:
        if e > peak: peak, peak_day = e, day
        if peak: mdd = max(mdd, (peak - e) / peak)
    return mdd, peak_day

def stats(st):
    c = RUN.vdb(st.code)
    acct = c.execute("SELECT * FROM account WHERE id=1").fetchone()
    cyc = c.execute("SELECT COUNT(*) n, MIN(ts_prepare) a, SUM(CASE WHEN ts_finish IS NOT NULL THEN 1 ELSE 0 END) f, "
                    "COALESCE(SUM(passed),0) p, COALESCE(SUM(buys),0) b FROM vcycles").fetchone()
    opens = c.execute("SELECT * FROM positions WHERE status IN ('OPEN','HALTED')").fetchall()
    closed = c.execute("SELECT * FROM positions WHERE status='CLOSED'").fetchall()
    mv = sum((r["qty"] or 0) * (r["last_price"] or r["entry_price"] or 0) for r in opens)
    unreal = mv - sum(r["cost"] or 0 for r in opens)
    realized = sum(r["realized_pnl"] or 0 for r in closed)
    wins = sum(1 for r in closed if (r["realized_pnl"] or 0) > 0)
    costs = c.execute("SELECT COALESCE(SUM(fee),0) f, COALESCE(SUM(tax),0) t, COALESCE(SUM(other_fee),0) o FROM fills WHERE action IN ('BUY','SELL')").fetchone()
    eq = acct["cash"] + mv
    eod = c.execute("SELECT day, equity, equity_krw FROM equity WHERE kind='EOD' ORDER BY day").fetchall()
    fx_now, fx_src, fx_day = M.fx_mark(M.mdb())
    start_krw = C.START_BALANCE_KRW
    eq_krw = eq if st.currency == "KRW" else eq * fx_now
    ret_ccy = eq / acct["start_balance"] - 1
    ret_krw = eq_krw / start_krw - 1
    mdd_ccy, _ = _mdd([(r["day"], r["equity"]) for r in eod], acct["start_balance"])
    mdd_krw, peak_day = _mdd([(r["day"], r["equity_krw"]) for r in eod], start_krw)
    out = {"book": st.code, "market": st.market, "currency": st.currency, "cycles": cyc["n"], "cycles_finished": cyc["f"], "screened": cyc["p"], "buys": cyc["b"],
           "open": len(opens), "closed": len(closed), "realized": round(realized, 2), "unrealized": round(unreal, 2),
           "cash": round(acct["cash"], 2), "equity": round(eq, 2), "equity_krw": round(eq_krw, 0),
           "ret_pct_ccy": round(ret_ccy * 100, 2), "ret_pct_krw": round(ret_krw * 100, 2), "fx_effect_pct": round((ret_krw - ret_ccy) * 100, 2),
           "win_rate": (round(wins / len(closed), 3) if closed else None), "mdd_pct_ccy": round(mdd_ccy * 100, 2), "mdd_pct_krw": round(mdd_krw * 100, 2),
           "peak_day": peak_day, "fees": round(costs["f"], 2), "taxes": round(costs["t"], 2), "other_fees": round(costs["o"], 4),
           "eod_days": len(eod), "last_eod": eod[-1]["day"] if eod else None, "halted": bool(kv_get(c, "halted", False)),
           "fx_now": fx_now if st.currency == "USD" else None, "fx_source": fx_src if st.currency == "USD" else None,
           "first_cycle": kst_str(cyc["a"]) if cyc["a"] else None}
    out["judge_models"] = {f"{r['m'] or 'unknown'}/{r['e'] or 'unknown'}": r["n"] for r in c.execute(
        "SELECT model m, effort e, COUNT(*) n FROM vjudge WHERE job_id IS NOT NULL GROUP BY model, effort ORDER BY n DESC")}
    out["slot_last"] = {k[len("slot_last:"):]: v["day"] for k, v in
                        ((r["k"], json.loads(r["v"])) for r in c.execute("SELECT k, v FROM kv WHERE k LIKE 'slot_last:%'"))}
    return out

def series(books, freq="daily", since=None):
    """[(day, {book: ret_pct_krw})] from EOD rows; weekly = last EOD of each ISO week. Missing days carry the previous value."""
    per = {}
    for st in books:
        c = RUN.vdb(st.code)
        rows = c.execute("SELECT day, equity_krw FROM equity WHERE kind='EOD'" + (" AND day>=?" if since else "") + " ORDER BY day", (since,) if since else ()).fetchall()
        per[st.code] = {r["day"]: r["equity_krw"] / C.START_BALANCE_KRW * 100 - 100 for r in rows}
    days = sorted({d for m in per.values() for d in m})
    out, last = [], {st.code: None for st in books}
    for d in days:
        for code in last:
            if d in per[code]: last[code] = per[code][d]
        out.append((d, dict(last)))
    if freq == "weekly":
        import datetime
        byweek = {}
        for d, row in out: byweek[datetime.date.fromisoformat(d).isocalendar()[:2]] = (d, row)
        out = [byweek[k] for k in sorted(byweek)]
    return out

def _fmt(x, w=9, pct=False):
    if x is None: return f"{'-':>{w}}"
    return f"{x:>{w}.2f}" if not pct else f"{x:>{w - 1}.2f}%"

if __name__ == "__main__":
    a = sys.argv[1:]
    books = strategies.enabled()
    if "--series" in a:
        freq = a[a.index("--series") + 1] if a.index("--series") + 1 < len(a) else "daily"
        since = a[a.index("--since") + 1] if "--since" in a else None
        rows = series(books, freq, since)
        codes = [st.code for st in books]
        if "--csv" in a:
            path = a[a.index("--csv") + 1]
            with open(path, "w", newline="") as f:
                w = csv.writer(f); w.writerow(["day"] + codes)
                for d, r in rows: w.writerow([d] + [("" if r[c] is None else f"{r[c]:.4f}") for c in codes])
            print(f"wrote {path} ({len(rows)} rows)"); sys.exit()
        if "--json" in a: print(json.dumps([{"day": d, **r} for d, r in rows], indent=1)); sys.exit()
        print(f"KRW-normalized return % since start (₩{C.START_BALANCE_KRW:,.0f} per book), {freq}, EOD marks only")
        print(f"{'day':>10}  " + "  ".join(f"{c:>8}" for c in codes))
        for d, r in rows: print(f"{d:>10}  " + "  ".join(_fmt(r[c], 8) for c in codes))
        print("MDD% (KRW) / peak day:")
        for st in books:
            s = stats(st); print(f"  {st.code:>6}: {s['mdd_pct_krw']:.2f}%  peak {s['peak_day'] or '-'}  last EOD {s['last_eod'] or '-'}")
        sys.exit()
    rows = [stats(st) for st in books]
    if "--json" in a: print(json.dumps(rows, indent=1, ensure_ascii=False)); sys.exit()
    print(f"Stock paper report  {kst_str()}  (equity = cash + qty*last mark; unrealized has no exit costs; KRW uses the latest fx_daily mark)")
    hdr = ["book", "ccy", "cycles", "buys", "open", "closed", "realized", "unreal", "equity", "ret%ccy", "ret%KRW", "fx%", "MDD%KRW", "win", "fees", "taxes", "lastEOD"]
    print("  ".join(f"{h:>8}" for h in hdr))
    for r in rows:
        vals = [r["book"], r["currency"], r["cycles"], r["buys"], r["open"], r["closed"], f"{r['realized']:.2f}", f"{r['unrealized']:.2f}", f"{r['equity']:.2f}",
                f"{r['ret_pct_ccy']:.2f}", f"{r['ret_pct_krw']:.2f}", f"{r['fx_effect_pct']:.2f}", f"{r['mdd_pct_krw']:.2f}",
                "-" if r["win_rate"] is None else f"{r['win_rate'] * 100:.0f}%", f"{r['fees']:.2f}", f"{r['taxes']:.2f}", r["last_eod"] or "-"]
        print("  ".join(f"{str(x):>8}" for x in vals) + ("  HALTED" if r["halted"] else ""))
    print("judge model/effort (judged decisions):")
    for r in rows: print(f"  {r['book']:>6}: " + (", ".join(f"{k} {n}" for k, n in r["judge_models"].items()) or "-"))
    print("last slot run per book: " + "; ".join(f"{r['book']} " + ",".join(f"{k}={v}" for k, v in sorted(r["slot_last"].items())) for r in rows if r["slot_last"]))
    print(gen_rules_doc.legend())
