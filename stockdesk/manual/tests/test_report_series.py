"""Return-trajectory report: EOD series (daily/weekly), KRW normalization for USD books, carry-forward, MDD and peak day."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done
import config as C
import run as RUN
import report as REP
import marketdb as M
import strategies
import common

krw = RUN.vdb("MO"); usd = RUN.vdb("MO-US")
check("USD book funded via fx_convert_once", abs(common.cash(usd) - C.START_BALANCE_USD) < 1e-3 and common.kv_get(usd, "fx_start")["krw_per_usd"] == C.FX_START_KRW_PER_USD)
check("USD book recorded an FX_FUND fill", usd.execute("SELECT COUNT(*) n FROM fills WHERE action='FX_FUND'").fetchone()["n"] == 1)

def eod(c, day, equity, fx=None):
    eq_krw = equity if fx is None else equity * fx
    c.execute("INSERT INTO equity (ts,day,kind,cash,equity,realized,unrealized,deployed,fx_rate,fx_source,equity_krw) VALUES (0,?,?,?,?,0,0,0,?,?,?)",
              (day, "EOD", equity, equity, fx, "test" if fx else None, eq_krw))
days = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03"]
for d, e in zip(days, [1_000_000, 1_020_000, 1_050_000, 1_000_000, 980_000, 1_010_000, 1_040_000]): eod(krw, d, e)
for d, e, fx in zip(days[:5], [714.29, 714.29, 720.0, 730.0, 740.0], [1400, 1420, 1400, 1380, 1400]): eod(usd, d, e, fx)
krw.execute("INSERT INTO equity (ts,day,kind,cash,equity,realized,unrealized,deployed,fx_rate,fx_source,equity_krw) VALUES (0,'2026-10-29','INTRA',1,1,0,0,0,NULL,NULL,1)")

books = [strategies.REGISTRY["MO"], strategies.REGISTRY["MO-US"]]
s = REP.series(books, "daily")
check("daily series spans all EOD days", [d for d, _ in s] == days)
check("INTRA rows ignored", abs(s[3][1]["MO"] - 0.0) < 1e-9)
check("KRW book return % = equity/1e6-1", abs(s[2][1]["MO"] - 5.0) < 1e-9)
check("USD book normalized to KRW: 714.29*1420/1e6", abs(s[1][1]["MO-US"] - (714.29 * 1420 / 1e6 * 100 - 100)) < 1e-6, s[1][1])
check("carry-forward when a book has no EOD that day", s[6][1]["MO-US"] == s[4][1]["MO-US"])
w = REP.series(books, "weekly")
check("weekly = last EOD of each ISO week", [d for d, _ in w] == ["2026-10-30", "2026-11-03"], [d for d, _ in w])
since = REP.series(books, "daily", since="2026-10-29")
check("--since filters", [d for d, _ in since][0] == "2026-10-29")

st = REP.stats(strategies.REGISTRY["MO"])
check("MDD from EOD KRW series (1.05M -> 0.98M = 6.67%)", abs(st["mdd_pct_krw"] - 6.67) < 0.01 and st["peak_day"] == "2026-10-28", (st["mdd_pct_krw"], st["peak_day"]))
check("report has ret% ccy and KRW, fees, taxes, last EOD", st["last_eod"] == "2026-11-03" and {"ret_pct_ccy", "ret_pct_krw", "fx_effect_pct", "fees", "taxes", "eod_days"} <= set(st))
M.put_fx(M.mdb(), "2026-11-03", 1500.0, "test")
su = REP.stats(strategies.REGISTRY["MO-US"])
check("USD stats use latest fx_daily for KRW return and show FX effect", su["fx_now"] == 1500.0 and abs(su["fx_effect_pct"] - (su["ret_pct_krw"] - su["ret_pct_ccy"])) < 1e-9, su)
done()
