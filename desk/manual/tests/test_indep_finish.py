# Scratch: cap overflow per book + finish mapping results back per book (fake Claude results, fake import). COPY of desk only.
import sys, json, os, glob, subprocess, types
os.environ["CLAUDE_CLI_MAX_JOBS"] = "7"
sys.path.insert(0, "/tmp/deskdry2"); sys.path.insert(0, "/tmp/deskdry2/manual")
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_indep.py")).read().split("rv.prepare()")[0].replace('os.environ["CLAUDE_CLI_MAX_JOBS"] = sys.argv[1] if len(sys.argv) > 1 else "40"', ""))
rv.prepare()
cyc = json.load(open(sorted(glob.glob("/tmp/deskdry2/manual/variant_cycles/meme-var-*[0-9].json"))[-1]))
rid = cyc["run_id"]; rundir = f"/tmp/deskdry2_store/{rid}"
print("jobs", len(cyc["jobs"]), "over cap by book", {b: sum(1 for u in cyc["unjudged_over_cap"] if u["book"] == b) for b in rv.VARIANTS})
assert len(cyc["jobs"]) == 7
# fake stored.jsonl: BASE says BUY p.30 b1 ; A gets SKIP word but p.6 b2 (EV>0) ; others SKIP
with open(f"{rundir}/stored.jsonl", "w") as f:
    for j in cyc["jobs"]:
        pj = {"BASE": {"decision": "SKIP", "confidence": .5, "p_win": .3, "payoff_ratio": 1.0, "rationale": "fake"},
              "A": {"decision": "SKIP", "confidence": .5, "p_win": .6, "payoff_ratio": 2.0, "rationale": "fake"}}.get(j["book"],
              {"decision": "SKIP", "confidence": .4, "p_win": .2, "payoff_ratio": 1.0, "rationale": "fake-" + j["book"]})
        f.write(json.dumps({"jobId": j["id"], "ok": True, "parsedJson": pj, "durationMs": 1, "claudeModel": "fake", "apiKeySource": "none"}) + "\n")
# runner results.jsonl: one valid new-format line (requestedModel/effort) + one bad line that must be skipped, not crash finish
open(f"{rundir}/results.jsonl", "w").write(json.dumps({"id": cyc["jobs"][0]["id"], "ok": True, "requestedModel": "fable", "requestedEffort": "medium"}) + "\nx\n")
assert rv.runner_requested(rundir) == {cyc["jobs"][0]["id"]: ("fable", "medium")}
rv.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="[import] fake ok", stderr=""))
rv.finish(rid)
res = json.load(open(f"/tmp/deskdry2/manual/variant_cycles/{rid}.result.json"))
for v in rv.VARIANTS:
    print(v, [(d["symbol"], d["decision"], d["rule"][:30]) for d in res["variants"][v]["decisions"]])
judged = {(j["book"], j["token"]) for j in cyc["jobs"]}
for v in rv.VARIANTS:
    for d in res["variants"][v]["decisions"]:
        if (v, d["token"]) in judged: assert d["rule"] != "OVER_JOB_CAP" and d["p_win"] is not None
        else: assert d["rule"] == "OVER_JOB_CAP", (v, d)
assert all(d["decision"] == "BUY" for d in res["variants"]["A"]["decisions"] if d["rule"].startswith("EV"))
print("FINISH MAPPING TEST OK")
