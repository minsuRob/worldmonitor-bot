"""Named market slots and trading-day logic. Strategies refer to slots by NAME only; this module owns them.

Slots (local market time). "llm" slots split into prepare/finish and are driven by the routine (manual/ROUTINE.md);
code-only slots are run by the box cron: `manual/variants.sh due --run`.
"""
import datetime, json, os, sys
from zoneinfo import ZoneInfo
import config as C

KST, ET = ZoneInfo(C.TZ), ZoneInfo(C.US_TZ)
TZ_OF = {"KRX": KST, "US": ET}

SLOTS = {
    # name:        market, local time (HH:MM), llm, phase names it serves, description
    "krx_open":  {"market": "KRX", "time": "09:05", "llm": False, "grace_min": 25,
                  "desc": "open marks -> RISK -> fill PENDING orders at the open -> strategy exits -> equity (INTRA)"},
    "krx_cb":    {"market": "KRX", "time": "15:00", "llm": True, "grace_min": 15, "finish_by": "15:20",
                  "desc": "closing-bet screen on live ranking -> jobs (veto) -> finish: PENDING orders for the closing auction"},
    "krx_close": {"market": "KRX", "time": "15:40", "llm": False, "grace_min": 60,
                  "desc": "close marks -> fill closing-auction orders -> EOD equity (the base for the next day's daily-loss check)"},
    "krx_after": {"market": "KRX", "time": "18:30", "llm": True, "grace_min": 60, "finish_by": "19:30",
                  "desc": "after-close screens (DART, flow, events, weekly momentum, theme) -> jobs -> finish: PENDING for next open"},
    "us_open":   {"market": "US", "time": "09:35", "llm": False, "grace_min": 25,
                  "desc": "US open marks -> RISK -> fill PENDING at the open -> exits"},
    "us_close":  {"market": "US", "time": "16:10", "llm": False, "grace_min": 60,
                  "desc": "US close marks -> EOD equity -> fx_daily mark"},
    "us_er":     {"market": "US", "time": "17:00", "llm": True, "grace_min": 60, "finish_by": "18:00",
                  "desc": "after-close earnings screen (+ weekly US momentum) -> jobs -> finish: PENDING for next open"},
}
NEXT_FILL_SLOT = {"KRX": "krx_open", "US": "us_open"}      # "OPEN_NEXT" orders fill here
EOD_SLOT = {"KRX": "krx_close", "US": "us_close"}

_holidays = {}
def holidays(market, year):
    key = (market, year)
    if key not in _holidays:
        p = os.path.join(C.DATA, f"holidays_{market}_{year}.json")
        try: _holidays[key] = set(json.load(open(p))["dates"])
        except (OSError, KeyError, ValueError): _holidays[key] = set()
    return _holidays[key]

def is_trading_day(market, day):
    """day: 'YYYY-MM-DD' in the market's local date."""
    d = datetime.date.fromisoformat(day)
    return d.weekday() < 5 and day not in holidays(market, d.year)

def next_trading_day(market, day):
    d = datetime.date.fromisoformat(day)
    while True:
        d += datetime.timedelta(days=1)
        if is_trading_day(market, d.isoformat()): return d.isoformat()

def prev_trading_day(market, day):
    d = datetime.date.fromisoformat(day)
    while True:
        d -= datetime.timedelta(days=1)
        if is_trading_day(market, d.isoformat()): return d.isoformat()

def trading_days_between(market, day_from, day_to):
    """Number of trading days in (day_from, day_to]. 0 when day_to <= day_from."""
    if not day_from or day_to <= day_from: return 0
    n, d = 0, datetime.date.fromisoformat(day_from)
    end = datetime.date.fromisoformat(day_to)
    while d < end:
        d += datetime.timedelta(days=1)
        if is_trading_day(market, d.isoformat()): n += 1
    return n

def local_now(market, ts=None):
    ts = ts if ts is not None else datetime.datetime.now(datetime.timezone.utc).timestamp()
    return datetime.datetime.fromtimestamp(ts, TZ_OF[market])

def slot_date(slot, ts=None):
    """Market-local date the slot belongs to (US evening slots in KST are still that US trading day)."""
    return local_now(SLOTS[slot]["market"], ts).strftime("%Y-%m-%d")

def slot_start(slot, day):
    s = SLOTS[slot]; hh, mm = map(int, s["time"].split(":"))
    return datetime.datetime.fromisoformat(day).replace(hour=hh, minute=mm, tzinfo=TZ_OF[s["market"]])

def due(ts, already_run, llm=None):
    """Slots whose window (start .. start+grace) contains ts on a trading day and that `already_run(slot, day)` says are not done.
    llm: None = all, False = code-only slots (box cron), True = LLM slots."""
    out = []
    for name, s in SLOTS.items():
        if llm is not None and s["llm"] != llm: continue
        day = slot_date(name, ts)
        if not is_trading_day(s["market"], day): continue
        st = slot_start(name, day).timestamp()
        if st <= ts <= st + s["grace_min"] * 60 and not already_run(name, day): out.append((name, day))
    return out

def kst_times(day=None):
    """{slot: 'HH:MM KST'} for a given date (US slots shift with DST)."""
    day = day or datetime.date.today().isoformat(); out = {}
    for name in SLOTS:
        out[name] = slot_start(name, day).astimezone(KST).strftime("%H:%M")
    return out

def assignments(registry):
    """Rows for ROUTINE.md: slot -> strategies screening / filling / exiting there."""
    rows = []
    for name, s in SLOTS.items():
        scr = [st.code for st in registry if st.slots.get("screen") == name]
        fil = [st.code for st in registry if st.slots.get("fill_entry") == name]
        ex = [st.code for st in registry if name in (st.slots.get("exits") or ())]
        rows.append({"slot": name, "market": s["market"], "time": s["time"], "llm": s["llm"], "screen": scr, "fill_entry": fil, "exits": ex})
    return rows

if __name__ == "__main__":
    if "--assignments" in sys.argv:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import strategies
        kt = kst_times()
        print("| 슬롯 | 시장 | 현지 시각 | KST(오늘) | LLM | 스크린 | 진입 체결 | 매도 |")
        print("|---|---|---|---|---|---|---|---|")
        for r in assignments(strategies.enabled()):
            print(f"| `{r['slot']}` | {r['market']} | {r['time']} | {kt[r['slot']]} | {'예' if r['llm'] else '아니오'} | "
                  f"{', '.join(r['screen']) or '-'} | {', '.join(r['fill_entry']) or '-'} | {', '.join(r['exits']) or '-'} |")
    else:
        for k, v in kst_times().items(): print(k, v, SLOTS[k]["desc"])
