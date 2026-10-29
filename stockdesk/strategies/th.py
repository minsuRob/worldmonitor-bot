"""TH 테마 로테이션: ONE job per day — Claude reads today's top gainers and disclosure headlines, names the theme money is
flowing into and its leader + second stock. Both are bought at the next open (leader bigger). EV rule from the same answer."""
import json
from .base import Strategy, Candidate

TH_SYSTEM = """You are the THEME JUDGE for ONE paper book of a PAPER-ONLY (simulated) Korean stock desk. No real money is involved.
This book (TH, "theme rotation") buys the leader and the runner-up of the theme that attracted the most money TODAY and holds a few days with a stop-loss. You are given today's top gainers (code, name, % change, turnover, sector) and today's disclosure headlines.
Name the single strongest theme (a group of >= 3 of the listed stocks moving together for one reason), pick its leader (largest turnover among them) and its second stock, both FROM THE LIST ONLY. If no coherent theme exists, or the move is a one-day spike with no catalyst, answer SKIP.
Return ONLY one JSON object, no prose, exactly:
{"decision":"BUY"|"SKIP","theme":string,"leader":string (6-digit code),"second":string (6-digit code),"confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}
p_win = probability the theme continues enough to exit at a profit within this book's holding period; payoff_ratio = average win / average loss."""

class TH(Strategy):
    code, name, market = "TH", "LLM 테마 로테이션", "KRX"
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    needs_llm = True
    buy_mode = "ev"
    system_prompt = TH_SYSTEM
    max_tokens = 500
    PARAMS = {"top_gainers": 40, "size_frac_leader": 0.15, "size_frac_second": 0.10, "size_frac": 0.15, "max_open": 4,
              "max_hold_days": 5, "stop": 0.08}   # ASSUMED

    def screen(self, ctx):
        """One synthetic candidate 'THEME' carrying the whole list; finish() expands it into leader/second via expand()."""
        uni = {u["code"]: u for u in ctx.universe}
        rows = ctx.snap.rank("change_pct", self.p("top_gainers"))
        if len(rows) < 3: return []
        gainers = [{"code": r["code"], "name": uni.get(r["code"], {}).get("name"), "change_pct": round(r["change_pct"] or 0, 2),
                    "turnover": r["turnover"], "sector": uni.get(r["code"], {}).get("sector"), "flags": ctx.snap.flags(r["code"])} for r in rows]
        heads = [{"code": d["stock_code"], "name": d["corp_name"], "title": d["report_nm"]} for d in ctx.snap.c.execute(
            "SELECT * FROM disclosures WHERE rcept_dt=? ORDER BY rcept_no LIMIT 60", (ctx.day,))]
        return [Candidate("KRX", "THEME", "today's theme", score=1.0, screen_json={"top_gainers": gainers, "disclosure_headlines": heads, "date": ctx.day})]

    def expand(self, cand, judge_json, universe):
        """(code, name, size_frac, instrument, signal) rows for the leader and second named by Claude, only if they were in the list."""
        if not isinstance(judge_json, dict): return []
        listed = {g["code"]: g for g in cand.screen_json.get("top_gainers", [])}
        uni = {u["code"]: u for u in universe}
        out = []
        for key, frac in (("leader", self.p("size_frac_leader")), ("second", self.p("size_frac_second"))):
            code = str(judge_json.get(key, "")).strip()
            if code in listed and code not in {o[0] for o in out}:
                out.append((code, listed[code].get("name") or "", frac, uni.get(code, {}).get("instrument") or "STOCK",
                            {"theme": judge_json.get("theme"), "role": key, **listed[code]}))
        return out

    def describe(self, lang="ko"):
        d = super().describe(lang); p = self.PARAMS
        d["screen"] = {"ko": f"상승률 상위 {p['top_gainers']} + 당일 공시 제목 → Claude가 테마·대장·2등 지정 (하루 1회 판단)",
                       "en": f"top {p['top_gainers']} gainers + today's filing titles -> Claude names theme, leader, second (one judgment a day)"}[lang]
        d["size"] = {"ko": f"대장 {p['size_frac_leader'] * 100:g}%, 2등 {p['size_frac_second'] * 100:g}%, 최대 {p['max_open']}개",
                     "en": f"leader {p['size_frac_leader'] * 100:g}%, second {p['size_frac_second'] * 100:g}%, max {p['max_open']} open"}[lang]
        return d
