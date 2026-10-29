"""MO 중기 모멘텀 / 52주 신고가 (KRX): 12-1 month momentum top N near the 52-week high, rebalanced once a week.
Pure numeric; the BASE-like benchmark book. mo_us.py reuses this screen for the US universe."""
import datetime
from .base import Strategy, Candidate

class MomentumMixin:
    PARAMS = {"top_n": 10, "lookback": 252, "skip": 20, "high52_prox": 0.10, "rebal_weekday": 4, "size_frac": 0.10, "max_open": 10}   # ASSUMED

    def universe_filter(self, rows):
        """Stocks only: ETFs/ETNs (e.g. CD-rate money-market ETFs that sit at their 52w high) are not momentum names."""
        return [r for r in super().universe_filter(rows) if (r.get("instrument") or "STOCK") == "STOCK"]

    def is_rebalance_day(self, day):
        return datetime.date.fromisoformat(day).weekday() == self.p("rebal_weekday")

    def momentum_screen(self, ctx):
        if not self.is_rebalance_day(ctx.day): return []
        out = []
        for row in self.universe_filter(ctx.universe):
            bars = ctx.snap.bars(row["code"], self.p("lookback") + 1)
            if len(bars) < self.p("lookback") * 0.9: continue
            end = bars[-1 - self.p("skip")] if len(bars) > self.p("skip") else bars[-1]
            start = bars[0]
            if not start["c"] or not end["c"]: continue
            mom = end["c"] / start["c"] - 1
            hi52 = max(b["h"] for b in bars[-252:])
            if bars[-1]["c"] < hi52 * (1 - self.p("high52_prox")): continue
            out.append(Candidate(self.market, row["code"], row.get("name") or "", score=mom,
                                 screen_json={"mom_12_1_pct": round(mom * 100, 2), "close": bars[-1]["c"], "high52": hi52, "rebalance_day": ctx.day},
                                 instrument=row.get("instrument") or "STOCK"))
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:self.p("top_n")]

    def momentum_exits(self, pos, mark, ctx):
        """On a rebalance day, drop positions that no longer make the list (runs through Strategy.exits in run._exits)."""
        if not self.is_rebalance_day(ctx.day): return None
        keep = {c.code for c in self.momentum_screen(ctx)}
        return None if pos["code"] in keep else "MO_REBALANCE_OUT"

    def momentum_describe(self, d, lang):
        p = self.PARAMS; wd = ["월", "화", "수", "목", "금"][p["rebal_weekday"]] if lang == "ko" else ["Mon", "Tue", "Wed", "Thu", "Fri"][p["rebal_weekday"]]
        d["screen"] = {"ko": f"{wd}요일마다 {p['lookback']}-{p['skip']}일 모멘텀 상위 {p['top_n']}, 52주 고가 {p['high52_prox'] * 100:g}% 이내",
                       "en": f"every {wd}: {p['lookback']}-{p['skip']}d momentum top {p['top_n']}, within {p['high52_prox'] * 100:g}% of the 52w high"}[lang]
        d["exits"] += {"ko": ", 리밸런스 날 목록에서 빠지면 매도", "en": ", sold when it drops off the list on a rebalance day"}[lang]
        return d

class MO(MomentumMixin, Strategy):
    code, name, market = "MO", "중기 모멘텀 (KRX, 주간)", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    PARAMS = dict(MomentumMixin.PARAMS)
    def screen(self, ctx): return self.momentum_screen(ctx)
    def exits(self, pos, mark, ctx): return self.momentum_exits(pos, mark, ctx)
    def describe(self, lang="ko"): return self.momentum_describe(super().describe(lang), lang)
