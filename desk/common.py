import json, os, sqlite3, time, urllib.request, urllib.error, datetime, logging
from zoneinfo import ZoneInfo
import config as C

KST = ZoneInfo(C.TZ)
os.makedirs(C.STATE, exist_ok=True); os.makedirs(C.LOGS, exist_ok=True); os.makedirs(C.REPORTS, exist_ok=True)

def now(): return time.time()
def kst(ts=None): return datetime.datetime.fromtimestamp(ts if ts is not None else time.time(), KST)
def kst_str(ts=None): return kst(ts).strftime("%Y-%m-%d %H:%M:%S KST")
def kst_day(ts=None): return kst(ts).strftime("%Y-%m-%d")
def day_start_ts(day=None):
    d = datetime.datetime.strptime(day or kst_day(), "%Y-%m-%d").replace(tzinfo=KST)
    return d.timestamp()

def logger(name):
    lg = logging.getLogger(name)
    if not lg.handlers:
        h = logging.FileHandler(os.path.join(C.LOGS, f"{name}.log"))
        h.setFormatter(logging.Formatter("%(asctime)s KST %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        lg.addHandler(h); lg.setLevel(logging.INFO)
    return lg

def http_json(url, method="GET", body=None, timeout=12, headers=None):
    """Returns (status, json_or_None, latency_ms, error_str). Never raises."""
    assert "api.worldmonitor.app" not in url, "forbidden endpoint"
    h = {"User-Agent": C.UA, "Accept": "application/json"}
    if headers: h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
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

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id=1), cash REAL, start_balance REAL, created_ts REAL);
CREATE TABLE IF NOT EXISTS health (bot TEXT PRIMARY KEY, pid INTEGER, last_hb REAL, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, bot TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS scan_drops (id INTEGER PRIMARY KEY, ts REAL, token TEXT, symbol TEXT, pair TEXT, reason TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY, ts REAL, token TEXT, symbol TEXT, pair TEXT, dex TEXT,
  liquidity REAL, fdv REAL, mcap REAL, price REAL, pair_created REAL, score REAL, holders INTEGER, holders_source TEXT,
  warnings TEXT, data TEXT, status TEXT, vet_result TEXT, vet_check TEXT, vet_detail TEXT, vet_ts REAL);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, candidate_id INTEGER, bet_id INTEGER, position_id INTEGER,
  token TEXT, symbol TEXT, pair TEXT, side TEXT, kelly_raw REAL, kelly_capped REAL, dollars REAL, expected_price REAL,
  status TEXT, reason TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS fills (id INTEGER PRIMARY KEY, ts REAL, order_id INTEGER, position_id INTEGER, action TEXT, token TEXT, symbol TEXT,
  requested_usd REAL, filled_usd REAL, partial INTEGER, expected_price REAL, fill_price REAL, slippage_bps REAL, fee REAL,
  qty REAL, over_limit INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, kind TEXT, token TEXT, symbol TEXT, pair TEXT, side TEXT, market TEXT,
  opened_ts REAL, qty REAL, cost_usd REAL, entry_price REAL, entry_mcap REAL, entry_liq REAL, peak_price REAL, peak_mcap REAL,
  last_price REAL, last_mcap REAL, last_ts REAL, adds INTEGER DEFAULT 0, flagged_60 INTEGER DEFAULT 0,
  status TEXT, closed_ts REAL, close_rule TEXT, close_detail TEXT, proceeds_usd REAL, realized_pnl REAL, miss_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY, ts REAL, wm_id TEXT, title TEXT, venue TEXT, venue_id TEXT, side TEXT,
  model_prob REAL, model_source TEXT, market_price REAL, edge REAL, data_ts REAL, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY, ts REAL, name TEXT, ok INTEGER, http INTEGER, latency_ms REAL, first_line TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS equity (id INTEGER PRIMARY KEY, ts REAL, cash REAL, equity REAL, realized REAL, unrealized REAL, deployed REAL);
"""

def db():
    c = sqlite3.connect(C.DB, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000")
    return c

def init_db():
    c = db(); c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM account").fetchone():
        c.execute("INSERT INTO account VALUES (1,?,?,?)", (C.START_BALANCE, C.START_BALANCE, now()))
    return c

def kv_get(c, k, default=None):
    r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default
def kv_set(c, k, v): c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))

def event(c, bot, kind, detail):
    c.execute("INSERT INTO events (ts,bot,kind,detail) VALUES (?,?,?,?)", (now(), bot, kind, json.dumps(detail, ensure_ascii=False) if not isinstance(detail, str) else detail))

def heartbeat(c, bot, status="ok", detail=""):
    c.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?,?)", (bot, os.getpid(), now(), status, detail))

def halted(c): return bool(kv_get(c, "halted", False))
def degraded(c): return bool(kv_get(c, "degraded", True))

def fee_for(dollars): return max(C.FEE_RATE * dollars, C.FEE_MIN)

def amm_buy(price, usd, liq):
    """Constant-product model: quote reserve ~ liq/2. Returns avg fill price for spending usd."""
    q = max(liq / 2.0, 1e-9)
    return price * (1 + usd / q)
def amm_sell(price, usd_value, liq):
    q = max(liq / 2.0, 1e-9)
    return price / (1 + usd_value / q)

def cash(c): return c.execute("SELECT cash FROM account WHERE id=1").fetchone()["cash"]
def encumbered(c):
    r = c.execute("SELECT COALESCE(SUM(dollars),0) s FROM orders WHERE status='SIZED'").fetchone()
    return r["s"]

def best_pairs(addresses):
    """DexScreener tokens/v1 batched (<=30). Returns ({token: best_pair_by_liquidity}, errors)."""
    out, errs = {}, []
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i+30]
        st, j, lat, err = http_json(f"{C.DEX}/tokens/v1/solana/{','.join(chunk)}")
        if st != 200 or not isinstance(j, list):
            errs.append(err or f"HTTP {st}"); continue
        for p in j:
            if p.get("chainId") != "solana": continue
            t = (p.get("baseToken") or {}).get("address")
            if t not in chunk: continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if t not in out or liq > ((out[t].get("liquidity") or {}).get("usd") or 0):
                out[t] = p
    return out, errs

def pair_by_address(pair):
    st, j, lat, err = http_json(f"{C.DEX}/latest/dex/pairs/solana/{pair}")
    if st == 200 and j and j.get("pairs"):
        return j["pairs"][0], None
    return None, err or f"HTTP {st} no pairs"

def mark_positions(c):
    """Unrealized PnL from last RISK-measured prices (no new fetch). Mark = qty*last_price (no exit costs)."""
    rows = c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
    mv = sum((r["qty"] or 0) * (r["last_price"] or r["entry_price"] or 0) for r in rows)
    cost = sum(r["cost_usd"] or 0 for r in rows)
    return rows, mv, mv - cost
