"""DT 공시 추종 (DART disclosure follow-through): Claude reads today's filings of the kinds that tend to re-rate a stock
and judges whether the news is real and still has room; EV rule decides. Hold days to weeks with stop/trail."""
from .base import Strategy, Candidate

DT_SYSTEM = """You are the JUDGE for ONE paper book of a PAPER-ONLY (simulated) Korean stock desk. No real money is involved.
This book (DT, "disclosure follow-through") buys at the NEXT OPEN after a DART filing and holds for days to weeks (stop-loss and trailing stop apply). You are given the filing title/summary, the stock's recent price action, flow and flags.
Judge whether the filing is a genuine, material positive that the market is likely to keep pricing in over the next 1-3 weeks. Be skeptical of: one-off gains, contracts small relative to revenue or spread over many years, cancellable or conditional deals, related-party deals, buybacks that are tiny, filings from stocks already up >50% in a month, and anything that reads like promotion. A filing that is clearly priced in on the day it was published (huge gap, then fade) is also a SKIP.
Return ONLY one JSON object, no prose, exactly:
{"decision":"BUY"|"SKIP","confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}
p_win = probability the trade is closed at a profit under this book's exits; payoff_ratio = average win / average loss. Give honest numbers even when you SKIP."""

class DT(Strategy):
    code, name, market = "DT", "공시 추종 (DART follow-through)", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    needs_llm = True
    buy_mode = "ev"
    system_prompt = DT_SYSTEM
    PARAMS = {"keywords": ("단일판매", "공급계약", "자기주식취득", "무상증자", "최대주주변경", "영업(잠정)실적", "잠정실적"),
              "max_month_gain": 0.50, "size_frac": 0.15, "max_open": 5, "stop": 0.07, "trail_after": 0.10, "trail": 0.10, "max_hold_days": 15}   # ASSUMED

    def screen(self, ctx):
        out, seen = [], set()
        uni = {u["code"]: u for u in self.universe_filter(ctx.universe)}
        for d in ctx.snap.disclosures(self.code):
            code = (d["stock_code"] or "").strip()
            if not code or code in seen or code not in uni: continue
            title = d["report_nm"] or ""
            if not any(k in title for k in self.p("keywords")): continue
            bars = ctx.snap.bars(code, 22)
            if len(bars) < 22: continue
            month_gain = bars[-1]["c"] / bars[-22]["c"] - 1
            if month_gain > self.p("max_month_gain"): continue
            flow = ctx.snap.flow(code, 5)
            seen.add(code)
            out.append(Candidate("KRX", code, uni[code].get("name") or d["corp_name"] or "", score=1.0 - month_gain,
                                 screen_json={"rcept_no": d["rcept_no"], "report": title, "summary": d["summary"], "filer": d["flr_nm"],
                                              "close": bars[-1]["c"], "month_gain_pct": round(month_gain * 100, 2),
                                              "last5_close": [b["c"] for b in bars[-5:]],
                                              "flow5_foreign": [f["foreign_net"] for f in flow], "flow5_inst": [f["inst_net"] for f in flow],
                                              "flags": ctx.snap.flags(code)},
                                 instrument=uni[code].get("instrument") or "STOCK"))
        return out

    def describe(self, lang="ko"):
        d = super().describe(lang); p = self.PARAMS
        d["screen"] = {"ko": f"당일 DART 공시 제목에 {'/'.join(p['keywords'][:4])} 등, 1개월 상승 ≤{p['max_month_gain'] * 100:g}%, 유니버스 안",
                       "en": f"today's DART filings titled {'/'.join(p['keywords'][:4])} ..., 1-month gain <= {p['max_month_gain'] * 100:g}%, in universe"}[lang]
        return d
