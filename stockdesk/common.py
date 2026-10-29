"""Shared helpers for the PAPER-ONLY stock desk.

출처: desk/common.py (2026-10-29 복사·개명). Copied, not imported: desk/common.py does a bare `import config`
and creates directories at import time, so importing it from here would be ambiguous once both packages have a
config.py. Solana parts (AMM fills, token config, DexScreener) were dropped; the time helpers, logger, http_json,
SQLite open, kv/event/heartbeat and the ledger schema shape are kept.
"""
import json, os, sqlite3, time, urllib.request, urllib.error, urllib.parse, datetime, logging
from zoneinfo import ZoneInfo
import config as C

KST = ZoneInfo(C.TZ)
ET = ZoneInfo(C.US_TZ)
for _d in (C.STATE, C.LOGS, C.BOOKS_DIR, C.CYCLES_DIR):
    os.makedirs(_d, exist_ok=True)

def now(): return time.time()
def kst(ts=None): return datetime.datetime.fromtimestamp(ts if ts is not None else time.time(), KST)
def kst_str(ts=None): return kst(ts).strftime("%Y-%m-%d %H:%M:%S KST")
def kst_day(ts=None): return kst(ts).strftime("%Y-%m-%d")
def et(ts=None): return datetime.datetime.fromtimestamp(ts if ts is not None else time.time(), ET)
def et_day(ts=None): return et(ts).strftime("%Y-%m-%d")
def day_start_ts(day=None, tz=KST):
    return datetime.datetime.strptime(day or kst_day(), "%Y-%m-%d").replace(tzinfo=tz).timestamp()

def logger(name):
    lg = logging.getLogger(name)
    if not lg.handlers:
        h = logging.FileHandler(os.path.join(C.LOGS, f"{name}.log"))
        h.setFormatter(logging.Formatter("%(asctime)s KST %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        lg.addHandler(h); lg.setLevel(logging.INFO)
    return lg

def http_json(url, method="GET", body=None, timeout=12, headers=None, form=None):
    """Returns (status, json_or_None, latency_ms, error_str). Never raises.
    body -> JSON; form -> application/x-www-form-urlencoded (OAuth token endpoints)."""
    assert "api.worldmonitor.app" not in url, "forbidden endpoint"
    h = {"User-Agent": C.UA, "Accept": "application/json"}
    if headers: h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode(); h["Content-Type"] = "application/x-www-form-urlencoded"
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout) as r:
            raw = r.read(); lat = (time.perf_counter() - t0) * 1000
            try: return r.status, json.loads(raw), lat, None
            except Exception as e: return r.status, None, lat, f"bad json: {e}"
    except urllib.error.HTTPError as e:
        lat = (time.perf_counter() - t0) * 1000
        try: j = json.loads(e.read())
        except Exception: j = None
        return e.code, j, lat, f"HTTP {e.code}"
    except Exception as e:
        return None, None, (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}"

def http_text(url, timeout=12, headers=None):
    """(status, text_or_None, latency_ms, err). For CSV endpoints (public fallbacks). Never raises."""
    assert "api.worldmonitor.app" not in url, "forbidden endpoint"
    h = {"User-Agent": C.UA}
    if headers: h.update(headers)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace"), (time.perf_counter() - t0) * 1000, None
    except urllib.error.HTTPError as e:
        return e.code, None, (time.perf_counter() - t0) * 1000, f"HTTP {e.code}"
    except Exception as e:
        return None, None, (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}"

# ---- per-book ledger schema (one SQLite file per strategy book)
BOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL, start_balance REAL, currency TEXT, created_ts REAL);
CREATE TABLE IF NOT EXISTS health (bot TEXT PRIMARY KEY, pid INTEGER, last_hb REAL, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, bot TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS equity (id INTEGER PRIMARY KEY, ts REAL, day TEXT, kind TEXT, cash REAL, equity REAL, realized REAL,
  unrealized REAL, deployed REAL, fx_rate REAL, fx_source TEXT, equity_krw REAL);
CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, slot TEXT, market TEXT, code TEXT, name TEXT,
  score REAL, screen_json TEXT, status TEXT, judge_id TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, slot TEXT, candidate_id INTEGER, position_id INTEGER,
  market TEXT, code TEXT, name TEXT, side TEXT, kind TEXT, qty_req REAL, value_req REAL, limit_px REAL,
  fill_at TEXT, expires_slot TEXT, status TEXT, reason TEXT, detail TEXT, signal_json TEXT);
CREATE TABLE IF NOT EXISTS fills (id INTEGER PRIMARY KEY, ts REAL, order_id INTEGER, position_id INTEGER, action TEXT, market TEXT, code TEXT,
  qty REAL, price REAL, value REAL, fee REAL, tax REAL, other_fee REAL, partial INTEGER, liquidity_ref TEXT, source TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, market TEXT, code TEXT, name TEXT, currency TEXT, strategy TEXT, instrument TEXT,
  qty REAL, entry_price REAL, entry_ts REAL, entry_day TEXT, cost REAL, peak_price REAL, last_price REAL, last_ts REAL, last_day TEXT,
  status TEXT, closed_ts REAL, close_rule TEXT, close_detail TEXT, proceeds REAL, realized_pnl REAL, signal_json TEXT,
  halted INTEGER DEFAULT 0, stale_days INTEGER DEFAULT 0, hold_days INTEGER DEFAULT 0, exit_slot TEXT);
CREATE TABLE IF NOT EXISTS vcycles (id INTEGER PRIMARY KEY, run_id TEXT UNIQUE, slot TEXT, book TEXT, ts_prepare REAL, ts_finish REAL,
  screened INTEGER, passed INTEGER, buys INTEGER, fills INTEGER, closes INTEGER, judged INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS vjudge (id INTEGER PRIMARY KEY, run_id TEXT, candidate_id INTEGER, market TEXT, code TEXT, job_id TEXT,
  claude_decision TEXT, confidence REAL, p_win REAL, payoff_ratio REAL, ev REAL, book_decision TEXT, rule TEXT, rationale TEXT, ts REAL,
  model TEXT, effort TEXT);
"""
ADDED_COLUMNS = ()   # (table, column, type) added after ledgers existed; older rows stay NULL

def open_db(path):
    c = sqlite3.connect(path, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000")
    return c

def migrate(c):
    for table, col, typ in ADDED_COLUMNS:
        if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

def kv_get(c, k, default=None):
    r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default
def kv_set(c, k, v): c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))

def event(c, bot, kind, detail):
    c.execute("INSERT INTO events (ts,bot,kind,detail) VALUES (?,?,?,?)",
              (now(), bot, kind, json.dumps(detail, ensure_ascii=False) if not isinstance(detail, str) else detail))

def heartbeat(c, bot, status="ok", detail=""):
    c.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?,?)", (bot, os.getpid(), now(), status, detail))

def cash(c): return c.execute("SELECT cash FROM account WHERE id=1").fetchone()["cash"]
def encumbered(c):
    """Cash reserved by not-yet-filled BUY orders."""
    return c.execute("SELECT COALESCE(SUM(value_req),0) s FROM orders WHERE status='PENDING' AND side='BUY'").fetchone()["s"]

def open_positions(c): return c.execute("SELECT * FROM positions WHERE status IN ('OPEN','HALTED') ORDER BY id").fetchall()

def mark_value(c):
    """(open_rows, market_value, unrealized) at the last recorded marks; no exit costs."""
    rows = open_positions(c)
    mv = sum((r["qty"] or 0) * (r["last_price"] or r["entry_price"] or 0) for r in rows)
    return rows, mv, mv - sum(r["cost"] or 0 for r in rows)

def equity_now(c):
    _, mv, _ = mark_value(c)
    return cash(c) + mv
