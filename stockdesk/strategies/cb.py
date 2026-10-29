"""CB 종가배팅 (closing bet): buy the day's strongest liquid movers in the 15:20 closing auction, sell at the next open.
Claude only has a VETO (flags such as 관리종목/투자경고, obvious one-day manipulation, news that is already fully priced)."""
from .base import Strategy, Candidate

CB_VETO_SYSTEM = """You are the VETO for ONE paper book of a PAPER-ONLY (simulated) Korean stock desk. No real money is involved.
This book (CB, "closing bet") buys the day's strongest, most-traded KRX stocks in the 15:20-15:30 closing auction on numeric signals and ALWAYS sells at the next day's open. It expects many small wins and some gap-down losses. Being a hot theme or up a lot today is NOT a reason to veto; that is the signal.
Your only job: veto (SKIP) when the data shows a CLEAR red flag for an overnight hold, for example: a caution/alert/administrative flag, a limit-up print that is purely one-day manipulation with collapsing turnover, a stock up on news that is already fully reflected (no room for a gap), an announced after-hours event that caps the next open (rights issue, lock-up expiry, large block sale), or a day-high far above the close (weak close). Otherwise answer BUY.
Return ONLY one JSON object, no prose, exactly:
{"decision":"BUY"|"SKIP","confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}
decision BUY = no veto, SKIP = veto. Still give honest p_win (probability the next open is above today's close after costs) and payoff_ratio (average gap-up / average gap-down)."""

class CB(Strategy):
    code, name, market = "CB", "종가배팅 (closing bet)", "KRX"
    slots = {"screen": "krx_cb", "fill_entry": "krx_close", "exits": ("krx_open",)}
    needs_llm = True
    buy_mode = "veto"
    system_prompt = CB_VETO_SYSTEM
    PARAMS = {"top_by_turnover": 30, "min_chg": 0.05, "max_chg": 0.25, "close_strength": 0.97, "new_high_days": 20,
              "min_turnover_krw": 2e10, "max_picks": 3, "size_frac": 0.30, "max_open": 3}   # ASSUMED

    def screen(self, ctx):
        out = []
        for r in ctx.snap.rank("turnover", self.p("top_by_turnover")):
            code = r["code"]
            if (r["turnover"] or 0) < self.p("min_turnover_krw"): continue
            chg = (r["change_pct"] or 0) / 100
            if not (self.p("min_chg") <= chg <= self.p("max_chg")): continue
            if r["high"] and r["price"] and r["price"] < r["high"] * self.p("close_strength"): continue
            bars = ctx.snap.bars(code, self.p("new_high_days") + 1)
            prev = [b for b in bars if b["date"] < ctx.day]
            if len(prev) < 5: continue
            hi = max(b["h"] for b in prev[-self.p("new_high_days"):])
            if r["price"] < hi: continue
            row = next((u for u in ctx.universe if u["code"] == code), {})
            out.append(Candidate("KRX", code, row.get("name") or (r["name"] if "name" in r.keys() else "") or "", score=r["turnover"],
                                 screen_json={"price": r["price"], "change_pct": r["change_pct"], "turnover_krw": r["turnover"], "day_high": r["high"],
                                              "close_strength": round(r["price"] / r["high"], 4) if r["high"] else None,
                                              f"high{self.p('new_high_days')}d_prev": hi, "auction_turnover_krw": r["auction_turnover"],
                                              "flags": ctx.snap.flags(code)},
                                 instrument=row.get("instrument") or "STOCK"))
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:self.p("max_picks")]

    def order_kind(self, cand): return "CLOSE_AUCTION", "krx_close"

    def exits(self, pos, mark, ctx):
        return "CB_SELL_NEXT_OPEN"   # always: the position is sold at the next open regardless of price

    def describe(self, lang="ko"):
        d = super().describe(lang); p = self.PARAMS
        d["screen"] = {"ko": f"15:00 거래대금 상위 {p['top_by_turnover']} 중 거래대금 ≥{p['min_turnover_krw'] / 1e8:g}억, 당일 +{p['min_chg'] * 100:g}~{p['max_chg'] * 100:g}%, "
                             f"종가/고가 ≥{p['close_strength']:g}, {p['new_high_days']}일 신고가; 상위 {p['max_picks']}개",
                       "en": f"top {p['top_by_turnover']} by turnover at 15:00, turnover >= {p['min_turnover_krw']:,.0f} KRW, day +{p['min_chg'] * 100:g}..{p['max_chg'] * 100:g}%, "
                             f"close/high >= {p['close_strength']:g}, {p['new_high_days']}d new high; best {p['max_picks']}"}[lang]
        d["exits"] = {"ko": "공통 RISK + **다음 시초가 항상 매도**", "en": "shared RISK + always sell at the next open"}[lang]
        d["size"] += {"ko": " (15:20 동시호가 체결, 동시호가 거래대금 상한)", "en": " (closing-auction fill, capped by auction turnover)"}[lang]
        return d
