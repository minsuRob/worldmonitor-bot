"""Trading days, holidays, slot windows (due), DST shift of US slots in KST, trading-day counting."""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done
import schedule as S

check("weekday is trading day", S.is_trading_day("KRX", "2026-10-29"))
check("Saturday is not", not S.is_trading_day("KRX", "2026-10-31"))
check("KRX holiday from data file (Chuseok 2026-09-25)", not S.is_trading_day("KRX", "2026-09-25"))
check("US holiday (Thanksgiving 2026-11-26)", not S.is_trading_day("US", "2026-11-26") and S.is_trading_day("KRX", "2026-11-26"))
check("next trading day skips weekend", S.next_trading_day("KRX", "2026-10-30") == "2026-11-02")
check("prev trading day", S.prev_trading_day("KRX", "2026-11-02") == "2026-10-30")
check("trading days between (Fri->Tue) = 2", S.trading_days_between("KRX", "2026-10-30", "2026-11-03") == 2)
check("trading days between same day = 0", S.trading_days_between("KRX", "2026-10-30", "2026-10-30") == 0)

# ---- slot start / KST times with and without DST
kt_summer = S.kst_times("2026-07-15"); kt_winter = S.kst_times("2026-12-15")
check("KRX slot KST fixed", kt_summer["krx_cb"] == "15:00" and kt_winter["krx_cb"] == "15:00")
check("US open 09:35 ET = 22:35 KST in summer, 23:35 in winter", kt_summer["us_open"] == "22:35" and kt_winter["us_open"] == "23:35", (kt_summer, kt_winter))
check("US close 16:10 ET = 05:10/06:10 KST", kt_summer["us_close"] == "05:10" and kt_winter["us_close"] == "06:10")

# ---- due windows
done_runs = set()
def already(slot, day): return (slot, day) in done_runs
ts = S.slot_start("krx_cb", "2026-10-29").timestamp() + 5 * 60
d = S.due(ts, already)
check("krx_cb due 5 min after 15:00", ("krx_cb", "2026-10-29") in d and all(s != "krx_open" for s, _ in d), d)
check("llm filter: code-only excludes krx_cb", ("krx_cb", "2026-10-29") not in S.due(ts, already, llm=False))
done_runs.add(("krx_cb", "2026-10-29"))
check("already run -> not due", ("krx_cb", "2026-10-29") not in S.due(ts, already))
ts2 = S.slot_start("krx_cb", "2026-10-29").timestamp() + 16 * 60
check("after grace (15 min) -> not due", not any(s == "krx_cb" for s, _ in S.due(ts2, lambda s, d: False)))
sat = S.slot_start("krx_close", "2026-10-31").timestamp() + 60
check("weekend -> nothing due", S.due(sat, lambda s, d: False) == [] or all(S.SLOTS[s]["market"] == "US" for s, _ in S.due(sat, lambda s, d: False)))
# US slot date is the ET date even when KST is already tomorrow
ts3 = S.slot_start("us_close", "2026-10-29").timestamp() + 60      # 16:11 ET Oct 29 = 05:11 KST Oct 30
check("us_close slot_date is the ET day", S.slot_date("us_close", ts3) == "2026-10-29" and S.slot_date("krx_open", ts3) == "2026-10-30")
check("every slot has finish_by only when llm", all(("finish_by" in s) == s["llm"] for s in S.SLOTS.values()))
check("NEXT_FILL/EOD slots exist", all(x in S.SLOTS for x in list(S.NEXT_FILL_SLOT.values()) + list(S.EOD_SLOT.values())))
done()
