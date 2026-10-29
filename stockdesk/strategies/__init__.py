"""Strategy registry: every strategies/<name>.py that does not start with '_' must define exactly one Strategy subclass.

Validation (ValueError -> prepare refuses to start):
  code unique and == module name upper-cased with '_' -> '-' (mo_us.py -> "MO-US")
  slots name existing schedule.SLOTS entries of the same market; needs_llm -> the screen slot has an LLM leg
  needs_llm -> non-empty system_prompt; buy_mode valid
  OVERRIDES keys exist in config and are not risk.PROTECTED_KEYS; the module never imports risk
Order is file-name sorted -> deterministic job round-robin and report columns. STOCKDESK_BOOKS=CB,MO limits enabled().
"""
import importlib, inspect, os, pkgutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config as C
import schedule as S
from risk import PROTECTED_KEYS
from .base import Strategy, Candidate, Ctx

BUY_MODES = ("code", "claude", "ev", "veto")

def discover():
    reg = {}
    for m in sorted(x.name for x in pkgutil.iter_modules([HERE])):
        if m.startswith("_") or m == "base": continue
        mod = importlib.import_module(f"{__name__}.{m}")
        src = inspect.getsource(mod)
        if "import risk" in src or "from risk" in src: raise ValueError(f"{m}: strategies must not import risk")
        classes = [v for v in vars(mod).values() if inspect.isclass(v) and issubclass(v, Strategy) and v is not Strategy and v.__module__ == mod.__name__]
        if len(classes) != 1: raise ValueError(f"{m}: expected exactly one Strategy subclass, found {len(classes)}")
        st = classes[0]()
        _validate(m, st)
        if st.code in reg: raise ValueError(f"duplicate strategy code {st.code}")
        reg[st.code] = st
    return reg

def _validate(m, st):
    if st.code != m.upper().replace("_", "-"): raise ValueError(f"{m}: code {st.code!r} must equal module name -> {m.upper().replace('_', '-')!r}")
    if st.market not in ("KRX", "US"): raise ValueError(f"{st.code}: market {st.market!r}")
    for k in ("screen", "fill_entry"):
        if st.slots.get(k) not in S.SLOTS: raise ValueError(f"{st.code}: slots[{k!r}]={st.slots.get(k)!r} not in schedule.SLOTS")
        if S.SLOTS[st.slots[k]]["market"] != st.market: raise ValueError(f"{st.code}: slot {st.slots[k]} is not a {st.market} slot")
    for e in st.slots.get("exits") or ():
        if e not in S.SLOTS: raise ValueError(f"{st.code}: exit slot {e!r} not in schedule.SLOTS")
    if st.needs_llm and not S.SLOTS[st.slots["screen"]]["llm"]:   # numeric books may screen in any slot (they skip the LLM leg)
        raise ValueError(f"{st.code}: needs_llm but slot {st.slots['screen']} has no LLM leg (schedule.SLOTS llm=False)")
    if st.needs_llm and not (st.system_prompt or "").strip(): raise ValueError(f"{st.code}: needs_llm without system_prompt")
    if st.buy_mode not in BUY_MODES: raise ValueError(f"{st.code}: buy_mode {st.buy_mode!r}")
    if not st.needs_llm and st.buy_mode != "code": raise ValueError(f"{st.code}: buy_mode {st.buy_mode!r} needs an LLM")
    for k in st.OVERRIDES:
        if not hasattr(C, k): raise ValueError(f"{st.code}: OVERRIDES key {k!r} not in config")
        if k in PROTECTED_KEYS: raise ValueError(f"{st.code}: OVERRIDES must not touch RISK key {k!r}")

REGISTRY = discover()

def enabled():
    flt = {x.strip().upper() for x in C.BOOKS_FILTER.split(",") if x.strip()}
    return [s for s in REGISTRY.values() if s.enabled and (not flt or s.code in flt)]

def by_code(code): return REGISTRY[code]

def for_slot(slot, phase):
    """phase: screen | fill_entry | exits."""
    out = []
    for s in enabled():
        if phase == "exits":
            if slot in (s.slots.get("exits") or ()): out.append(s)
        elif s.slots.get(phase) == slot: out.append(s)
    return out
