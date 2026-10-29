"""Test harness: copy stockdesk/ into a temp dir so state/, logs/ and the Claude CLI store never touch the real desk.
Pattern: desk/manual/tests/test_books_v2.py (temp copy + monkeypatched fetchers). Import this FIRST in every test."""
import os, shutil, sys, tempfile
os.environ["STOCKDESK_FAKE_SNAPSHOT"] = "1"
os.environ.pop("STOCKDESK_BOOKS", None)
for k in ("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET", "DART_API_KEY", "FINNHUB_API_KEY"): os.environ.pop(k, None)
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="stockdesk-test-")
DESK = os.path.join(TMP, "stockdesk")
shutil.copytree(SRC, DESK, ignore=shutil.ignore_patterns("state", "logs", "__pycache__", "variant_cycles", ".env*", "*.db", "*.db-*"))
os.environ["STOCKDESK_CLAUDE_CLI_STORE"] = os.path.join(TMP, "claude-cli")
sys.path.insert(0, DESK)
import config as C  # noqa: E402
assert C.BASE == DESK and C.STATE.startswith(TMP), (C.BASE, C.STATE)

OK = []
def check(name, cond, info=""):
    assert cond, f"FAIL {name} {info}"
    OK.append(name)
def done():
    print(f"ALL {len(OK)} CHECKS OK")
