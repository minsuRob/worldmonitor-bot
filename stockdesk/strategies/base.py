"""Strategy plugin base. Copy strategies/_template.py to add a new book; see docs/project/stockdesk/books.md.

A strategy declares WHAT it trades (market, slots, numbers in PARAMS) and HOW it screens; run.py owns the ledger,
locks, RISK, bans and fills. Numeric strategies override only screen() (and maybe exits()); LLM strategies add
needs_llm=True, system_prompt and buy_mode. Nothing here touches risk.py — RISK runs before any strategy code.
"""
from dataclasses import dataclass, field
import json
import config as C
import judge as J

@dataclass
class Candidate:
    market: str
    code: str
    name: str = ""
    score: float = 0.0
    screen_json: dict = field(default_factory=dict)
    instrument: str = "STOCK"
    id: int = None

@dataclass
class Ctx:
    """Read-only per-slot context built by run.py. `ban` cannot be bypassed: run.py subtracts it again after screen()."""
    slot: str
    day: str
    now: float
    market: str
    snap: object
    universe: list
    ban: set
    regime_block: str = ""
    lg: object = None
    book_state: dict = field(default_factory=dict)

class Strategy:
    code = "XX"
    name = "one-line description"
    market = "KRX"                       # KRX | US  (currency follows: KRW | USD)
    slots = {"screen": "krx_after", "fill_entry": "krx_open", "exits": ("krx_open",)}
    needs_llm = False
    system_prompt = None                 # required when needs_llm
    buy_mode = "code"                    # code | claude | ev | veto  (judge.decide)
    OVERRIDES = {}                       # config.py names this book changes (never risk.PROTECTED_KEYS)
    PARAMS = {}                          # strategy-only numbers; describe() and the rules table read them
    enabled = True
    max_tokens = 400

    @property
    def currency(self): return "KRW" if self.market == "KRX" else "USD"
    @property
    def cost(self): return C.ROUNDTRIP_COST[self.market]
    def p(self, k, d=None): return self.PARAMS.get(k, d)

    # ---- required
    def screen(self, ctx) -> list:
        raise NotImplementedError

    # ---- defaults
    def universe_filter(self, rows):
        if self.market == "US": return rows
        return [r for r in rows if (r.get("mcap") or 0) >= C.KRX_MIN_MCAP_KRW and (r.get("avg_turnover") or 0) >= C.KRX_MIN_AVG_TURNOVER_KRW]

    def user_prompt(self, ctx, cand):
        state = {"book": self.code, **ctx.book_state}
        return (f"Paper book {self.code} ({self.name}; independent {'₩1,000,000' if self.currency == 'KRW' else '$' + format(C.START_BALANCE_USD, ',.0f')} account) state:\n"
                + json.dumps(state, indent=1, ensure_ascii=False)
                + f"\nBook {self.code} rules: {self.rules_text()}\n\n"
                + f"Candidate ({self.market} {cand.code} {cand.name}), screen data:\n" + json.dumps(cand.screen_json, indent=1, ensure_ascii=False, default=str)
                + (("\n\n" + ctx.regime_block) if ctx.regime_block else ""))

    def build_job(self, ctx, cand, run_id):
        assert self.needs_llm and self.system_prompt, f"{self.code}: build_job needs system_prompt"
        return J.build_job(run_id, self.code, {"id": cand.id, "market": cand.market, "code": cand.code, "name": cand.name},
                           self.system_prompt, self.user_prompt(ctx, cand), self.max_tokens)

    def decide(self, judge_json):
        return J.decide(self.buy_mode, judge_json, self.cost)

    def size(self, equity, cand):
        """Planned entry value in the book currency (before RISK's cap_entry_value)."""
        return equity * float(self.p("size_frac", C.DEFAULT_SIZE_FRAC))

    def max_open(self): return self.p("max_open")

    def order_kind(self, cand):
        """(kind, fill_at_slot): OPEN_NEXT fills at the next open; CLOSE_AUCTION at the closing auction; LIMIT needs cand.screen_json['limit_px']."""
        return "OPEN_NEXT", self.slots["fill_entry"]

    def exits(self, pos, mark, ctx):
        """Return a rule string to sell the whole position now, or None. Default: stop / trail after gain / max hold days from PARAMS."""
        if mark is None or not pos["entry_price"]: return None
        stop = self.p("stop"); trail_after = self.p("trail_after"); trail = self.p("trail"); hold = self.p("max_hold_days")
        if stop and mark <= pos["entry_price"] * (1 - stop): return f"{self.code}_STOP_-{stop * 100:g}%"
        if trail and trail_after and (pos["peak_price"] or 0) >= pos["entry_price"] * (1 + trail_after) and mark <= pos["peak_price"] * (1 - trail):
            return f"{self.code}_TRAIL_-{trail * 100:g}%_AFTER_+{trail_after * 100:g}%"
        if hold and (pos["hold_days"] or 0) >= hold: return f"{self.code}_MAX_HOLD_{hold}D"
        return None

    def rules_text(self):
        d = self.describe("en")
        return f"Screen: {d['screen']} Size: {d['size']} Buy: {d['buy']} Exits: {d['exits']}"

    def describe(self, lang="ko"):
        """Rows for the generated rules table. Subclasses add their screen wording; the rest comes from PARAMS."""
        size = self.p("size_frac", C.DEFAULT_SIZE_FRAC) * 100; mo = self.max_open()
        buy = {"code": {"ko": "통과하면 매수 (LLM 없음)", "en": "every pass buys (no LLM)"},
               "claude": {"ko": "Claude `BUY`", "en": "Claude BUY/SKIP"},
               "ev": {"ko": f"EV = p_win×payoff − (1−p_win) − {self.cost:g} > 0", "en": f"EV = p_win*payoff - (1-p_win) - {self.cost:g} > 0"},
               "veto": {"ko": "수치 신호로 매수, Claude는 **거부권**만 (무응답 = SKIP)", "en": "numeric signal buys unless Claude vetoes (no answer = SKIP)"}}[self.buy_mode][lang]
        ex = []
        if self.p("stop"): ex.append({"ko": f"손절 −{self.p('stop') * 100:g}%", "en": f"stop -{self.p('stop') * 100:g}%"}[lang])
        if self.p("trail"): ex.append({"ko": f"+{self.p('trail_after') * 100:g}% 뒤 고점 대비 −{self.p('trail') * 100:g}%", "en": f"trail -{self.p('trail') * 100:g}% after +{self.p('trail_after') * 100:g}%"}[lang])
        if self.p("max_hold_days"): ex.append({"ko": f"최대 {self.p('max_hold_days')}거래일", "en": f"max {self.p('max_hold_days')} trading days"}[lang])
        exits = ({"ko": "공통 RISK", "en": "shared RISK"}[lang]) + ((" + " + ", ".join(ex)) if ex else "")
        return {"screen": "", "size": {"ko": f"잔고의 고정 {size:g}%" + (f", 최대 {mo}개 보유" if mo else ""),
                                       "en": f"fixed {size:g}% of equity" + (f", max {mo} open" if mo else "")}[lang], "buy": buy, "exits": exits}

    def extra_sql(self): return ""
    def on_fill(self, c, fill): pass

    # ---- helpers for screens
    @staticmethod
    def sma(bars, n, key="c"):
        xs = [b[key] for b in bars[-n:] if b[key] is not None]
        return sum(xs) / len(xs) if len(xs) == n else None
