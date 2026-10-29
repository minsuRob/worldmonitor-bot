"""Shared market cache: state/market.db (read-only market data, separate from the book ledgers).

Every slot fetches once and writes here; every book and the backtester read from here, so all books see the same
data. Every row carries `source` (toss / dart / krx / stooq / erapi / fake) so reports can say where a number came from.
"""
import json, os
import config as C
from common import open_db, now

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_daily (market TEXT, code TEXT, date TEXT, o REAL, h REAL, l REAL, c REAL, v REAL, turnover REAL,
  source TEXT, fetched_ts REAL, PRIMARY KEY (market, code, date));
CREATE TABLE IF NOT EXISTS intraday_snap (slot_date TEXT, slot TEXT, market TEXT, code TEXT, price REAL, open REAL, high REAL, low REAL,
  change_pct REAL, volume REAL, turnover REAL, auction_turnover REAL, high20 REAL, source TEXT, fetched_ts REAL,
  PRIMARY KEY (slot_date, slot, market, code));
CREATE TABLE IF NOT EXISTS flow_daily (market TEXT, code TEXT, date TEXT, foreign_net REAL, inst_net REAL, retail_net REAL, source TEXT,
  PRIMARY KEY (market, code, date));
CREATE TABLE IF NOT EXISTS disclosures (rcept_no TEXT PRIMARY KEY, corp_code TEXT, stock_code TEXT, corp_name TEXT, report_nm TEXT,
  rcept_dt TEXT, flr_nm TEXT, summary TEXT, fetched_ts REAL, judged_books TEXT);
CREATE TABLE IF NOT EXISTS calendar (id INTEGER PRIMARY KEY, market TEXT, code TEXT, event_type TEXT, date_announce TEXT, date_effective TEXT,
  ban_from TEXT, ban_to TEXT, source TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS flags (market TEXT, code TEXT, date TEXT, flags_json TEXT, source TEXT, PRIMARY KEY (market, code, date));
CREATE TABLE IF NOT EXISTS fx_daily (date TEXT PRIMARY KEY, krw_per_usd REAL, source TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS universe (market TEXT, code TEXT, name TEXT, instrument TEXT, sector TEXT, mcap REAL, avg_turnover REAL,
  updated_ts REAL, PRIMARY KEY (market, code));
CREATE TABLE IF NOT EXISTS earnings (market TEXT, code TEXT, date TEXT, when_ TEXT, eps_est REAL, eps_act REAL, rev_est REAL, rev_act REAL,
  source TEXT, PRIMARY KEY (market, code, date));
CREATE TABLE IF NOT EXISTS slot_runs (slot TEXT, day TEXT, ts REAL, run_id TEXT, phase TEXT, PRIMARY KEY (slot, day));
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

class KVStore:
    """dict-like get/set over market.db kv (shared Toss token cache; state/ is gitignored, never printed)."""
    def __init__(self, c): self.c = c
    def get(self, k, default=None):
        r = self.c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default
    def __setitem__(self, k, v): self.c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))
    def __getitem__(self, k):
        v = self.get(k)
        if v is None: raise KeyError(k)
        return v

def slot_done(c, slot, day):
    return c.execute("SELECT 1 FROM slot_runs WHERE slot=? AND day=?", (slot, day)).fetchone() is not None

def mark_slot(c, slot, day, run_id, phase):
    c.execute("INSERT OR REPLACE INTO slot_runs VALUES (?,?,?,?,?)", (slot, day, now(), run_id, phase))

_conn = None
def mdb(path=None):
    global _conn
    if path is not None:
        c = open_db(path); c.executescript(MARKET_SCHEMA); return c
    if _conn is None:
        _conn = open_db(C.MARKET_DB); _conn.executescript(MARKET_SCHEMA)
        try: os.chmod(C.MARKET_DB, 0o600)   # kv holds the Toss access token
        except OSError: pass
    return _conn

def reset():
    """Drop the cached connection (tests that swap C.MARKET_DB)."""
    global _conn
    _conn = None

# ---- bars
def put_bars(c, market, code, rows, source):
    """rows: iterable of dicts {date,o,h,l,c,v,turnover}. Upsert."""
    t = now()
    c.executemany("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  [(market, code, r["date"], r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v"), r.get("turnover"), source, t) for r in rows])

def get_bars(c, market, code, n, asof=None):
    """Last n daily bars with date <= asof (inclusive), oldest first."""
    q = "SELECT * FROM bars_daily WHERE market=? AND code=?" + (" AND date<=?" if asof else "") + " ORDER BY date DESC LIMIT ?"
    args = (market, code, asof, n) if asof else (market, code, n)
    return list(reversed(c.execute(q, args).fetchall()))

def put_snap(c, slot_date, slot, market, rows, source):
    t = now()
    c.executemany("INSERT OR REPLACE INTO intraday_snap VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [(slot_date, slot, market, r["code"], r.get("price"), r.get("open"), r.get("high"), r.get("low"), r.get("change_pct"),
                    r.get("volume"), r.get("turnover"), r.get("auction_turnover"), r.get("high20"), source, t) for r in rows])

def get_snap(c, slot_date, slot, market):
    return {r["code"]: r for r in c.execute("SELECT * FROM intraday_snap WHERE slot_date=? AND slot=? AND market=?", (slot_date, slot, market))}

# ---- flow / flags / calendar / disclosures
def put_flow(c, market, rows, source):
    c.executemany("INSERT OR REPLACE INTO flow_daily VALUES (?,?,?,?,?,?,?)",
                  [(market, r["code"], r["date"], r.get("foreign_net"), r.get("inst_net"), r.get("retail_net"), source) for r in rows])

def get_flow(c, market, code, n, asof=None):
    q = "SELECT * FROM flow_daily WHERE market=? AND code=?" + (" AND date<=?" if asof else "") + " ORDER BY date DESC LIMIT ?"
    args = (market, code, asof, n) if asof else (market, code, n)
    return list(reversed(c.execute(q, args).fetchall()))

def put_flags(c, market, date, flags_by_code, source):
    c.executemany("INSERT OR REPLACE INTO flags VALUES (?,?,?,?,?)",
                  [(market, code, date, json.dumps(sorted(fl), ensure_ascii=False), source) for code, fl in flags_by_code.items()])

def get_flags(c, market, date):
    """{code: [flags]} for the latest flags row on or before date."""
    out = {}
    for r in c.execute("SELECT code, flags_json FROM flags WHERE market=? AND date=(SELECT MAX(date) FROM flags WHERE market=? AND date<=?)",
                       (market, market, date)):
        out[r["code"]] = json.loads(r["flags_json"])
    return out

def put_calendar(c, market, code, event_type, date_announce, date_effective, ban_from, ban_to, source, detail=""):
    if c.execute("SELECT 1 FROM calendar WHERE market=? AND code=? AND event_type=? AND date_effective=?",
                 (market, code, event_type, date_effective)).fetchone():
        return
    c.execute("INSERT INTO calendar (market,code,event_type,date_announce,date_effective,ban_from,ban_to,source,detail) VALUES (?,?,?,?,?,?,?,?,?)",
              (market, code, event_type, date_announce, date_effective, ban_from, ban_to, source, detail))

def ban_codes(c, market, date):
    return {r["code"] for r in c.execute("SELECT code FROM calendar WHERE market=? AND ban_from<=? AND ban_to>=?", (market, date, date))}

def calendar_events(c, market, event_type, date_from, date_to):
    return c.execute("SELECT * FROM calendar WHERE market=? AND event_type=? AND date_effective BETWEEN ? AND ? ORDER BY date_effective",
                     (market, event_type, date_from, date_to)).fetchall()

def put_disclosures(c, rows, source="dart"):
    """rows: DART list.json items. Returns the number of NEW rcept_no."""
    n = 0
    for r in rows:
        if c.execute("SELECT 1 FROM disclosures WHERE rcept_no=?", (r["rcept_no"],)).fetchone(): continue
        c.execute("INSERT INTO disclosures VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (r["rcept_no"], r.get("corp_code"), r.get("stock_code"), r.get("corp_name"), r.get("report_nm"), r.get("rcept_dt"),
                   r.get("flr_nm"), r.get("summary"), now(), "[]"))
        n += 1
    return n

def unjudged_disclosures(c, book, date):
    return [r for r in c.execute("SELECT * FROM disclosures WHERE rcept_dt=? ORDER BY rcept_no", (date,))
            if book not in json.loads(r["judged_books"] or "[]")]

def mark_disclosure_judged(c, rcept_no, book):
    r = c.execute("SELECT judged_books FROM disclosures WHERE rcept_no=?", (rcept_no,)).fetchone()
    if not r: return
    books = json.loads(r["judged_books"] or "[]")
    if book not in books: books.append(book)
    c.execute("UPDATE disclosures SET judged_books=? WHERE rcept_no=?", (json.dumps(books), rcept_no))

# ---- fx / universe / earnings
def put_fx(c, date, krw_per_usd, source):
    c.execute("INSERT OR REPLACE INTO fx_daily VALUES (?,?,?,?)", (date, krw_per_usd, source, now()))

def fx_mark(c, date=None):
    """(krw_per_usd, source, date) of the latest fx on or before date; config FX_START if none recorded."""
    q = "SELECT * FROM fx_daily" + (" WHERE date<=?" if date else "") + " ORDER BY date DESC LIMIT 1"
    r = c.execute(q, (date,) if date else ()).fetchone()
    if r: return r["krw_per_usd"], r["source"], r["date"]
    return C.FX_START_KRW_PER_USD, "config", None

def put_universe(c, market, rows):
    t = now()
    c.executemany("INSERT OR REPLACE INTO universe VALUES (?,?,?,?,?,?,?,?)",
                  [(market, r["code"], r.get("name"), r.get("instrument", "STOCK"), r.get("sector"), r.get("mcap"), r.get("avg_turnover"), t) for r in rows])

def universe(c, market):
    return [dict(r) for r in c.execute("SELECT * FROM universe WHERE market=? ORDER BY code", (market,))]

def put_earnings(c, market, rows, source):
    c.executemany("INSERT OR REPLACE INTO earnings VALUES (?,?,?,?,?,?,?,?,?)",
                  [(market, r["code"], r["date"], r.get("when"), r.get("eps_est"), r.get("eps_act"), r.get("rev_est"), r.get("rev_act"), source) for r in rows])

def earnings_on(c, market, date):
    return c.execute("SELECT * FROM earnings WHERE market=? AND date=?", (market, date)).fetchall()
