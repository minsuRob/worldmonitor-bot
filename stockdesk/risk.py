"""Common RISK for every book. Runs FIRST in every fill slot and is never overridden by a strategy.

Rules (config.py, PROTECTED_KEYS):
  HALT flags      거래정지 -> position HALTED (cannot trade); 관리종목/투자위험/정리매매/상장폐지 -> close at this slot's price
  stale marks     no price for > STALE_MAX_TRADING_DAYS -> flagged UNMEASURABLE; > STALE_CLOSE_TRADING_DAYS -> closed at last price
  position size   can_enter() caps one entry at MAX_POSITION_PCT of equity
  daily loss      book down > DAILY_LOSS_LIMIT_PCT today (vs last EOD) -> no new entries today
  drawdown halt   equity < peak*(1-MAX_DRAWDOWN_HALT_PCT) -> kv halted=True (user clears), no entries, exits keep running
Strategy exits (Strategy.exits) run AFTER this pass on the marks it wrote. Plugins must not import this module
and cannot put these keys in OVERRIDES (strategies/__init__.py checks).
"""
import json
import config as C
from common import now, event, kv_get, kv_set, equity_now, cash, open_positions
import fills as F

PROTECTED_KEYS = ("MAX_POSITION_PCT", "DAILY_LOSS_LIMIT_PCT", "MAX_DRAWDOWN_HALT_PCT", "STALE_MAX_TRADING_DAYS",
                  "STALE_CLOSE_TRADING_DAYS", "HALT_FLAGS", "BAN_FLAGS")
CLOSE_FLAGS = tuple(f for f in C.HALT_FLAGS if f != "거래정지")

def close_position(c, pos, px, rule, detail, ref="mark", bot="RISK"):
    """Sell the whole position at px: fills row, cash credit, position CLOSED. One transaction."""
    f = F.fill_at_price(pos["market"], "SELL", pos["qty"], px, pos["instrument"] or "STOCK", ref)
    costs = f["fee"] + f["tax"] + f["other"]
    proceeds = f["value"] - costs
    pnl = proceeds - (pos["cost"] or 0)
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_rule=?, close_detail=?, proceeds=?, realized_pnl=?, last_price=?, last_ts=? WHERE id=?",
                  (now(), rule, detail, proceeds, pnl, px, now(), pos["id"]))
        c.execute("UPDATE account SET cash=cash+? WHERE id=1", (proceeds,))
        c.execute("INSERT INTO fills (ts,order_id,position_id,action,market,code,qty,price,value,fee,tax,other_fee,partial,liquidity_ref,source,detail) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (now(), None, pos["id"], "SELL", pos["market"], pos["code"], f["qty"], px, f["value"], f["fee"], f["tax"], f["other"], 0, ref, bot, rule))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK"); raise
    event(c, bot, "CLOSE", {"code": pos["code"], "rule": rule, "px": px, "pnl": round(pnl, 2), "detail": detail})
    return pnl

def risk_pass(c, book, marks, flags, day, trading_days_since, lg=None):
    """marks: {code: price or None} for this slot; flags: {code: [flags]}; day: slot date (market local).
    trading_days_since(last_day, day) -> int. Updates marks/peaks/hold days, applies the rules above.
    Returns {"closed": n, "halted": n, "unmeasurable": n}."""
    out = {"closed": 0, "halted": 0, "unmeasurable": 0}
    for pos in open_positions(c):
        code = pos["code"]; px = marks.get(code)
        fl = set(flags.get(code, []))
        if px is not None and px > 0:
            peak = max(pos["peak_price"] or 0, px)
            hold = (pos["hold_days"] or 0) + (trading_days_since(pos["last_day"], day) if pos["last_day"] else 0)
            c.execute("UPDATE positions SET last_price=?, last_ts=?, last_day=?, peak_price=?, stale_days=0, hold_days=? WHERE id=?",
                      (px, now(), day, peak, hold, pos["id"]))
            pos = c.execute("SELECT * FROM positions WHERE id=?", (pos["id"],)).fetchone()
        else:
            stale = (pos["stale_days"] or 0) + 1
            c.execute("UPDATE positions SET stale_days=? WHERE id=?", (stale, pos["id"]))
            if stale > C.STALE_CLOSE_TRADING_DAYS and pos["last_price"]:
                close_position(c, pos, pos["last_price"], "UNMEASURABLE_CLOSE", f"no mark for {stale} trading days", "last")
                out["closed"] += 1; continue
            if stale > C.STALE_MAX_TRADING_DAYS:
                event(c, "RISK", "UNMEASURABLE", {"code": code, "stale_days": stale}); out["unmeasurable"] += 1
            continue
        if "거래정지" in fl:
            if pos["status"] != "HALTED":
                c.execute("UPDATE positions SET status='HALTED', halted=1 WHERE id=?", (pos["id"],))
                event(c, "RISK", "HALTED", {"code": code, "flags": sorted(fl)}); out["halted"] += 1
            continue
        if pos["status"] == "HALTED":   # suspension lifted -> back to OPEN, then the flag rules below
            c.execute("UPDATE positions SET status='OPEN' WHERE id=?", (pos["id"],))
        hit = fl & set(CLOSE_FLAGS)
        if hit:
            close_position(c, pos, px, "FLAG_" + "/".join(sorted(hit)), json.dumps(sorted(fl), ensure_ascii=False)); out["closed"] += 1
    _drawdown_check(c, book)
    return out

def _drawdown_check(c, book):
    eq = equity_now(c)
    peak = max(kv_get(c, "equity_peak", 0.0) or 0.0, eq)
    kv_set(c, "equity_peak", peak)
    if peak > 0 and eq < peak * (1 - C.MAX_DRAWDOWN_HALT_PCT) and not kv_get(c, "halted", False):
        kv_set(c, "halted", True)
        event(c, "RISK", "HALT", {"book": book, "equity": round(eq, 2), "peak": round(peak, 2), "rule": f"drawdown>{C.MAX_DRAWDOWN_HALT_PCT:g}"})

def daily_loss_blocked(c, day):
    """True when today's equity is more than DAILY_LOSS_LIMIT_PCT below the last EOD equity before today."""
    r = c.execute("SELECT equity FROM equity WHERE kind='EOD' AND day<? ORDER BY day DESC LIMIT 1", (day,)).fetchone()
    base = r["equity"] if r else c.execute("SELECT start_balance FROM account WHERE id=1").fetchone()["start_balance"]
    return base > 0 and equity_now(c) < base * (1 - C.DAILY_LOSS_LIMIT_PCT)

def can_enter(c, day):
    """(ok, reason). Entries are refused when halted or over the daily loss limit."""
    if kv_get(c, "halted", False): return False, "HALTED"
    if daily_loss_blocked(c, day): return False, "DAILY_LOSS_LIMIT"
    return True, ""

def cap_entry_value(c, value):
    """Entry value capped at MAX_POSITION_PCT of equity and at free cash."""
    from common import encumbered
    eq = equity_now(c)
    free = cash(c) - encumbered(c)
    return max(0.0, min(value, C.MAX_POSITION_PCT * eq, free))
