"""Judge job lines and result parsing for the box <-> Mac handoff (same runner as the legacy desk).

Job line (desk/manual/run_variants.py:333-337 format, pipeline "stock"):
  {"id","runId","pipeline":"stock","stage":"judge","book","promptHash","openrouterModel":null,"openrouterCacheKey":null,
   "maxTokens","responseFormat":"json_object","system","user","capturedAt","candidateId","market","code","name"}
Result line (desk/manual/mac/claude_cli_runner.sh): {id, ok, text, claudeModel, requestedModel, requestedEffort, durationMs, ...}
Broken result lines are skipped (never abort finish), as in run_variants.runner_requested.
"""
import hashlib, json, os, datetime
import config as C

RESPONSE_SCHEMA = '{"decision":"BUY"|"SKIP","confidence":number 0-1,"p_win":number 0-1,"payoff_ratio":number >0,"rationale":string (<= 40 words)}'

def build_job(run_id, book, cand, system, user, max_tokens=400):
    return {"id": f"{run_id}:{book}:{cand['market']}:{cand['code']}", "runId": run_id, "pipeline": "stock", "stage": "judge", "book": book,
            "promptHash": hashlib.sha256((system + "\0" + user).encode()).hexdigest()[:16],
            "openrouterModel": None, "openrouterCacheKey": None, "maxTokens": max_tokens, "responseFormat": "json_object",
            "system": system, "user": user,
            "capturedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "candidateId": cand.get("id"), "market": cand["market"], "code": cand["code"], "name": cand.get("name")}

def write_jobs(rundir, jobs):
    os.makedirs(rundir, exist_ok=True)
    p = os.path.join(rundir, "jobs.jsonl")
    with open(p, "w") as f:
        for j in jobs: f.write(json.dumps(j, ensure_ascii=False) + "\n")
    return p

def parse_text(text):
    """Claude's text -> dict or None. Tolerates a fenced block or prose around one JSON object."""
    if not text: return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"): t = t[4:]
    try:
        j = json.loads(t)
        return j if isinstance(j, dict) else None
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            try:
                j = json.loads(t[a:b + 1]); return j if isinstance(j, dict) else None
            except ValueError: return None
    return None

def read_results(rundir):
    """job id -> {ok, json, text, model, requested_model, effort, duration_ms}. Missing file -> None. Bad lines skipped."""
    p = os.path.join(rundir, "results.jsonl")
    if not os.path.exists(p): return None
    out = {}
    for line in open(p):
        if not line.strip(): continue
        try: rec = json.loads(line)
        except ValueError: continue
        if not isinstance(rec, dict) or "id" not in rec: continue
        out[rec["id"]] = {"ok": bool(rec.get("ok")), "json": parse_text(rec.get("text")) if rec.get("ok") else None, "text": rec.get("text"),
                          "model": rec.get("claudeModel"), "requested_model": rec.get("requestedModel"), "effort": rec.get("requestedEffort"),
                          "duration_ms": rec.get("durationMs")}
    return out

def _num(x, d=None):
    try: return float(x)
    except (TypeError, ValueError): return d

def ev_of(j, cost):
    """EV = p_win*payoff - (1-p_win) - cost; None when fields are missing."""
    if not isinstance(j, dict): return None
    p, b = _num(j.get("p_win")), _num(j.get("payoff_ratio"))
    if p is None or b is None: return None
    return p * b - (1 - p) - cost

def decide(buy_mode, j, cost):
    """(decision, rule, ev). buy_mode: code (no LLM, always BUY) | claude (BUY word) | ev (EV>0) | veto (BUY unless Claude says SKIP).
    j None = no judge result -> SKIP for every LLM mode (fail closed)."""
    if buy_mode == "code": return "BUY", "CODE", None
    if j is None: return "SKIP", "NO_JUDGE", None
    ev = ev_of(j, cost)
    word = str(j.get("decision", "")).upper()
    if buy_mode == "claude": return ("BUY" if word == "BUY" else "SKIP"), "CLAUDE", ev
    if buy_mode == "ev": return ("BUY" if ev is not None and ev > 0 else "SKIP"), f"EV>0 (cost {cost:g})", ev
    if buy_mode == "veto": return ("SKIP" if word == "SKIP" else "BUY" if word == "BUY" else "SKIP"), "VETO", ev
    raise ValueError(buy_mode)
