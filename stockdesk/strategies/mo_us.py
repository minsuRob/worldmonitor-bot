"""MO-US: the same weekly momentum / 52-week-high screen as MO, on the US universe (S&P500 + Nasdaq100 list in data/)."""
from .base import Strategy
from .mo import MomentumMixin

class MO_US(MomentumMixin, Strategy):
    code, name, market = "MO-US", "중기 모멘텀 (US, 주간)", "US"
    slots = {"screen": "us_er", "fill_entry": "us_open", "exits": ("us_open",)}
    needs_llm = False
    PARAMS = dict(MomentumMixin.PARAMS)
    def screen(self, ctx): return self.momentum_screen(ctx)
    def exits(self, pos, mark, ctx): return self.momentum_exits(pos, mark, ctx)
    def describe(self, lang="ko"): return self.momentum_describe(super().describe(lang), lang)
