"""새 전략 템플릿. 복사 → strategies/<code 소문자>.py (예: xx.py, 코드 "XX"; mo_us.py → "MO-US").
숫자는 PARAMS/OVERRIDES에만 둔다(규칙 표·프롬프트가 거기서 읽는다). RISK 키(risk.PROTECTED_KEYS)는 넣을 수 없다.
이 파일은 '_'로 시작해서 레지스트리가 건너뛴다."""
from .base import Strategy, Candidate

class XX(Strategy):
    code, name, market = "XX", "한 줄 설명", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    needs_llm = False            # True면 system_prompt와 buy_mode(claude|ev|veto)를 채우고 screen 슬롯은 llm=True인 슬롯이어야 한다
    PARAMS = {"size_frac": 0.15, "max_open": 5, "stop": 0.07, "max_hold_days": 10}   # ASSUMED

    def screen(self, ctx):
        out = []
        for row in self.universe_filter(ctx.universe):
            bars = ctx.snap.bars(row["code"], 21)
            if len(bars) < 21: continue
            sma20 = self.sma(bars, 20)
            if sma20 and bars[-1]["c"] > sma20:
                out.append(Candidate(self.market, row["code"], row.get("name") or "", score=bars[-1]["c"] / sma20,
                                     screen_json={"close": bars[-1]["c"], "sma20": sma20}, instrument=row.get("instrument") or "STOCK"))
        return out

    def describe(self, lang="ko"):
        d = super().describe(lang)
        d["screen"] = {"ko": "종가 > 20일선", "en": "close above 20DMA"}[lang]
        return d
