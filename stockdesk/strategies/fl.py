"""FL 수급 추종 (flow following): foreign + institutional net buying several days in a row while the price holds above
its 20DMA. Pure numeric. Needs flow_daily rows (source TBC; nothing is bought while flow data is absent)."""
from .base import Strategy, Candidate

class FL(Strategy):
    code, name, market = "FL", "수급 추종 (foreign+inst flow)", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    PARAMS = {"consec_days": 3, "min_net_krw": 1e9, "dma": 20, "size_frac": 0.15, "max_open": 5, "exit_sell_days": 2, "max_hold_days": 20}   # ASSUMED

    def screen(self, ctx):
        out = []
        for row in self.universe_filter(ctx.universe):
            code = row["code"]
            flow = ctx.snap.flow(code, self.p("consec_days"))
            if len(flow) < self.p("consec_days") or flow[-1]["date"] != ctx.day: continue
            if not all((f["foreign_net"] or 0) > 0 and (f["inst_net"] or 0) > 0 for f in flow): continue
            net = sum((f["foreign_net"] or 0) + (f["inst_net"] or 0) for f in flow)
            if net < self.p("min_net_krw"): continue
            bars = ctx.snap.bars(code, self.p("dma"))
            sma = self.sma(bars, self.p("dma"))
            if not sma or bars[-1]["c"] <= sma: continue
            out.append(Candidate("KRX", code, row.get("name") or "", score=net,
                                 screen_json={"net_krw": net, "days": self.p("consec_days"), "close": bars[-1]["c"], f"sma{self.p('dma')}": sma},
                                 instrument=row.get("instrument") or "STOCK"))
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def exits(self, pos, mark, ctx):
        base = super().exits(pos, mark, ctx)
        if base: return base
        flow = ctx.snap.flow(pos["code"], self.p("exit_sell_days"))
        if len(flow) == self.p("exit_sell_days") and all((f["foreign_net"] or 0) + (f["inst_net"] or 0) < 0 for f in flow):
            return f"FL_NET_SELL_{self.p('exit_sell_days')}D"
        return None

    def describe(self, lang="ko"):
        d = super().describe(lang); p = self.PARAMS
        d["screen"] = {"ko": f"외국인·기관 모두 {p['consec_days']}일 연속 순매수(합계 ≥{p['min_net_krw'] / 1e8:g}억), 종가 > {p['dma']}일선",
                       "en": f"foreign and institutions both net buyers {p['consec_days']} days in a row (sum >= {p['min_net_krw']:,.0f} KRW), close > {p['dma']}DMA"}[lang]
        d["exits"] += {"ko": f", 외국인+기관 {p['exit_sell_days']}일 연속 순매도", "en": f", foreign+inst net sellers {p['exit_sell_days']} days"}[lang]
        return d
