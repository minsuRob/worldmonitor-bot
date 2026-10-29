"""EV 이벤트 캘린더: v1 trades only announced index additions (KOSPI200/KOSDAQ150) bought before the effective date and sold
at the open of the effective day. Lock-up expiries are NOT traded; they feed the shared ban list (screen.ban_set via calendar).
Calendar rows come from marketdb.calendar (source TBC; the fake market seeds one)."""
import schedule as S
from .base import Strategy, Candidate

class EV(Strategy):
    code, name, market = "EV", "이벤트 캘린더 (index add)", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    PARAMS = {"event_types": ("INDEX_ADD",), "days_before_max": 10, "size_frac": 0.15, "max_open": 4, "stop": 0.08}   # ASSUMED

    def screen(self, ctx):
        out = []
        end = ctx.day
        for _ in range(self.p("days_before_max")): end = S.next_trading_day("KRX", end)
        uni = {u["code"]: u for u in ctx.universe}
        for et in self.p("event_types"):
            for e in ctx.snap.c.execute("SELECT * FROM calendar WHERE market='KRX' AND event_type=? AND date_effective>? AND date_effective<=?", (et, ctx.day, end)):
                code = e["code"]
                bars = ctx.snap.bars(code, 1)
                out.append(Candidate("KRX", code, uni.get(code, {}).get("name") or "", score=1.0,
                                     screen_json={"event": et, "effective": e["date_effective"], "announced": e["date_announce"], "detail": e["detail"],
                                                  "close": bars[-1]["c"] if bars else None, "sell_on": e["date_effective"]},
                                     instrument=uni.get(code, {}).get("instrument") or "STOCK"))
        return out

    def exits(self, pos, mark, ctx):
        base = super().exits(pos, mark, ctx)
        if base: return base
        import json
        sig = json.loads(pos["signal_json"] or "{}")
        if sig.get("sell_on") and ctx.day >= sig["sell_on"]: return "EV_EFFECTIVE_DAY_OPEN"
        return None

    def describe(self, lang="ko"):
        d = super().describe(lang); p = self.PARAMS
        d["screen"] = {"ko": f"발표된 지수 편입({'/'.join(p['event_types'])}) 종목, 효력일 {p['days_before_max']}거래일 전부터; 보호예수 해제는 매수 금지 필터",
                       "en": f"announced index additions ({'/'.join(p['event_types'])}) within {p['days_before_max']} trading days of the effective date; lock-up expiries only ban"}[lang]
        d["exits"] += {"ko": ", 효력일 시초가 매도", "en": ", sell at the open of the effective day"}[lang]
        return d
