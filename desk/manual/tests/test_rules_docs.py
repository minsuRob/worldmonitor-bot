"""The per-book rule tables in the docs must match the code (config.py / book_rules.py). No network, no files written.
  python3 manual/tests/test_rules_docs.py"""
import sys, os, subprocess
MANUAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MANUAL)
import gen_rules_doc as G, book_rules as BR
OK = []
def check(name, cond, info=""):
    assert cond, f"FAIL {name} {info}"; OK.append(name)

bad = G.check()
check("docs match code", not bad, "\n".join(d for _, _, d in bad) + "\n-> run: python3 manual/gen_rules_doc.py --write")
check("README has markers", G.BEGIN in open(G.DOCS["en"], encoding="utf-8").read())

# a changed number in the code must make the check fail (and show the new value)
old = BR.OVERRIDES["B"]["VET_TOP_HOLDER_MAX"]
BR.OVERRIDES["B"]["VET_TOP_HOLDER_MAX"] = 0.09
try:
    bad = G.check()
    check("changed override is detected", any(lang == "en" for lang, _, _ in bad), bad)
    check("diff shows the new value", any("top holder <=9%" in d for _, _, d in bad))
    check("legend follows the code", "B=top holder 9%" in G.legend(), G.legend())
finally:
    BR.OVERRIDES["B"]["VET_TOP_HOLDER_MAX"] = old
check("restored", not G.check())

# every book row has the same number of columns as its header
for lang in ("en", "ko"):
    lines = G.table(lang).splitlines()
    n = lines[0].count("|")
    check(f"{lang} column count", all(l.count("|") == n for l in lines), lang)

try: G.render("no markers here", "en"); check("missing markers raise", False)
except ValueError: check("missing markers raise", True)

r = subprocess.run([sys.executable, os.path.join(MANUAL, "gen_rules_doc.py"), "--check"], capture_output=True, text=True)
check("--check exits 0", r.returncode == 0, r.stdout + r.stderr)
print(f"ALL {len(OK)} CHECKS OK")
