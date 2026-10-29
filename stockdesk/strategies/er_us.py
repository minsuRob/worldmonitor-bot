"""ER-US 실적 발표 후 추세 (post-earnings drift): after-close reports that beat and that the after-market rewards;
Claude judges the quality of the beat (guidance, one-offs). EV rule; bought at the next US open, held ~2 weeks."""
from .base import Strategy, Candidate

ER_SYSTEM = """You are the JUDGE for ONE paper book of a PAPER-ONLY (simulated) US stock desk. No real money is involved.
This book (ER-US, "post-earnings drift") buys at the NEXT OPEN after an after-close earnings report and holds about two weeks with a stop-loss. You are given the reported vs estimated EPS/revenue, the after-hours price reaction, recent price action and the book's state.
Judge whether this is a HIGH-QUALITY beat the market will keep rewarding: revenue AND EPS beat, raised or confirmed guidance, broad-based rather than one-off (tax, asset sale, buyback-driven EPS), and a reaction that is positive but not already extreme. Skip beats on lowered bars, EPS-only beats, big after-hours spikes (>15%) that usually fade, or stocks that ran >30% into the print.
Return ONLY one JSON object, no prose, exactly:
{"decision":"BUY"|"SKIP","confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}
p_win = probability the trade is closed at a profit under this book's exits; payoff_ratio = average win / average loss."""

class ER_US(Strategy):
    code, name, market = "ER-US", "실적 발표 후 추세 (US PEAD)", "US"
    slots = {"screen": "us_er", "fill_entry": "us_open", "exits": ("us_open",)}
    needs_llm = True
    buy_mode = "ev"
    system_prompt = ER_SYSTEM
    PARAMS = {"min_gap": 0.04, "max_gap": 0.15, "max_run_in": 0.30, "size_frac": 0.15, "max_open": 5, "stop": 0.06, "max_hold_days": 10}   # ASSUMED

    def screen(self, ctx):
        out = []
        uni = {u["code"]: u for u in ctx.universe}
        for e in ctx.snap.earnings_today():
            code = e["code"]
            if code not in uni: continue
            if e["eps_est"] is None or e["eps_act"] is None or e["eps_act"] <= e["eps_est"]: continue
            bars = ctx.snap.bars(code, 22)
            if len(bars) < 22: continue
            snap = ctx.snap.snap(code)
            ah = snap["price"] if snap and snap["price"] else None     # after-hours price when the source provides it (TBC)
            gap = (ah / bars[-1]["c"] - 1) if ah and bars[-1]["c"] else None
            if gap is None or not (self.p("min_gap") <= gap <= self.p("max_gap")): continue
            run_in = bars[-1]["c"] / bars[0]["c"] - 1
            if run_in > self.p("max_run_in"): continue
            out.append(Candidate("US", code, uni[code].get("name") or "", score=gap,
                                 screen_json={"eps_est": e["eps_est"], "eps_act": e["eps_act"], "rev_est": e["rev_est"], "rev_act": e["rev_act"],
                                              "after_hours_gap_pct": round(gap * 100, 2), "run_in_1m_pct": round(run_in * 100, 2),
                                              "close": bars[-1]["c"], "last5_close": [b["c"] for b in bars[-5:]]}))
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def describe(self, lang="ko"):
        d = super().describe(lang); p = self.PARAMS
        d["screen"] = {"ko": f"장마감 후 실적 EPS 상회 + 애프터마켓 +{p['min_gap'] * 100:g}~{p['max_gap'] * 100:g}%, 1개월 선행 상승 ≤{p['max_run_in'] * 100:g}%",
                       "en": f"after-close EPS beat + after-hours +{p['min_gap'] * 100:g}..{p['max_gap'] * 100:g}%, 1-month run-in <= {p['max_run_in'] * 100:g}%"}[lang]
        return d
