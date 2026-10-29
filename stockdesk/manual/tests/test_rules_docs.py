"""Generated rules tables: markers, --check detects a PARAMS change, --write restores, missing markers -> ValueError.
Pattern: desk/manual/tests/test_rules_docs.py."""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done, DESK, TMP
import gen_rules_doc as G
import strategies

# temp docs with markers (the repo docs are checked by the real --check in the verification step)
docs = {}
for lang in ("en", "ko"):
    p = os.path.join(TMP, f"doc_{lang}.md"); docs[lang] = p
    open(p, "w", encoding="utf-8").write(f"# head\n\n{G.BEGIN}\nstale\n{G.END}\n\ntail\n")
G.DOCS = docs
check("stale table detected", len(G.check()) == 2)
for lang, p in docs.items():
    new = G.render(open(p, encoding="utf-8").read(), lang)
    open(p, "w", encoding="utf-8").write(new)
check("after write: tables OK", G.check() == [])
for lang in ("en", "ko"):
    t = G.table(lang)
    check(f"{lang}: one row per strategy + 2 header lines", len(t.splitlines()) == len(strategies.REGISTRY) + 2)
    check(f"{lang}: header column count matches rows", all(l.count("|") == G.HEADERS[lang][0].count("|") for l in t.splitlines()), t)
check("en table names ledgers", "state/books/CB.db" in G.table("en"))
# a PARAMS change is caught
cb = strategies.REGISTRY["CB"]; old = cb.PARAMS["max_picks"]; cb.PARAMS["max_picks"] = old + 1
try:
    bad = G.check(); check("PARAMS change -> check fails with diff", len(bad) == 2 and "max_picks" not in bad[0][2] and str(old + 1) in bad[0][2], bad[0][2][:300] if bad else bad)
finally: cb.PARAMS["max_picks"] = old
check("restored -> OK", G.check() == [])
try:
    G.render("no markers here", "en"); check("missing markers -> ValueError", False)
except ValueError: check("missing markers -> ValueError", True)
check("legend lists every book", all(code in G.legend() for code in strategies.REGISTRY))
# CLI --check on the repo docs (both present in the repo checkout)
r = subprocess.run([sys.executable, os.path.join(DESK, "gen_rules_doc.py"), "--check"], capture_output=True, text=True)
check("repo docs rules tables match code (run --write if this fails)", r.returncode == 0, r.stdout[-800:])
done()
