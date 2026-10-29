"""PAPER-ONLY stock desk configuration (KRX + US). No real orders, accounts, order/account API calls.

Only shared numbers live here: paths, balances/FX, costs, fill-model caps, universe, RISK and job caps.
Strategy-specific numbers live in each plugin's PARAMS (stockdesk/strategies/<code>.py) so the generated
rules table (gen_rules_doc.py) and the prompts read one source. Values marked ASSUMED are desk assumptions,
not measured estimates. TBC = to be confirmed against the official source.
"""
import os
BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state")
LOGS = os.path.join(BASE, "logs")
BOOKS_DIR = os.path.join(STATE, "books")          # one SQLite ledger per strategy book: <CODE>.db
MARKET_DB = os.path.join(STATE, "market.db")      # shared read-only market cache (bars, flow, disclosures, fx ...)
DATA = os.path.join(BASE, "data")                 # tracked static data: holidays, US universe, DART corp codes
CYCLES_DIR = os.path.join(BASE, "manual", "variant_cycles")   # <runId>.json / .result.json / slots-YYYYMMDD.jsonl (gitignored)
TZ = "Asia/Seoul"
US_TZ = "America/New_York"
UA = "stockdesk/0.1 (paper trading only; read-only market data)"

def _load_env_file(path):
    """KEY=VALUE lines into os.environ (existing env wins). stockdesk/.env is gitignored, mode 600."""
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
_load_env_file(os.path.join(BASE, ".env"))

# ---- secrets: NAMES only, values from env / .env. Never log or print them.
TOSS_CLIENT_ID = os.environ.get("TOSS_CLIENT_ID", "").strip()
TOSS_CLIENT_SECRET = os.environ.get("TOSS_CLIENT_SECRET", "").strip()
DART_API_KEY = os.environ.get("DART_API_KEY", "").strip()
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()

# ---- box <-> Mac judge handoff (same runner as the legacy desk: desk/manual/mac/claude_cli_runner.sh)
CLAUDE_CLI_STORE = os.environ.get("STOCKDESK_CLAUDE_CLI_STORE", "/workspace/worldmonitor/data/claude-cli")
MAX_JOBS = int(os.environ.get("CLAUDE_CLI_MAX_JOBS", "40"))      # must equal the runner's CLAUDE_CLI_MAX_JOBS
ROUTINE_VERSION = os.environ.get("STOCKDESK_ROUTINE_VERSION")    # set by the routine (manual/ROUTINE.md); None = not set
BOOKS_FILTER = os.environ.get("STOCKDESK_BOOKS", "")             # "CB,MO" -> run only these books (tests, staged rollout)
FAKE_SNAPSHOT = os.environ.get("STOCKDESK_FAKE_SNAPSHOT") == "1"  # offline dry run: synthetic market snapshot, no HTTP

# ---- balances and FX
START_BALANCE_KRW = 1_000_000.0          # every book starts here (KRW books directly, USD books converted once)
FX_START_KRW_PER_USD = 1400.0            # ASSUMED; the actual value used is recorded in the USD book (kv fx_start)
FX_CONVERSION_COST = 0.001               # ASSUMED one-time conversion cost when funding a USD book
START_BALANCE_USD = START_BALANCE_KRW / FX_START_KRW_PER_USD * (1 - FX_CONVERSION_COST)
FX_MARK_SOURCE_ORDER = ("toss", "erapi")   # TBC: first source that answers writes fx_daily

# ---- costs
KRX_FEE_RATE = 0.00015                   # broker fee each side (user-specified; event accounts can be lower)
KRX_TAX_SELL = {"KOSPI": 0.0020, "KOSDAQ": 0.0020, "ETF": 0.0}   # sell-side tax. User-specified 0.20%; TBC: statutory rate for the year
US_FEE_RATE = 0.0025                     # broker fee each side; 0.0007-0.0025 depending on the account
US_SEC_FEE_SELL = 0.0000278              # TBC (SEC section 31, changes yearly)
US_FINRA_TAF_PER_SHARE = 0.000166        # TBC
US_FINRA_TAF_MAX = 8.30                  # TBC
US_FRACTIONAL = True                     # Toss supports fractional US quantities (quantity "0.5")
US_QTY_STEP = 0.0001
ROUNDTRIP_COST = {"KRX": 0.006, "US": 0.0055}   # EV-rule cost: fees + tax + ASSUMED impact, per market

# ---- fill model (fills.py). All ASSUMED.
CB_AUCTION_CAP_PCT = 0.005               # closing-auction fill <= 0.5% of the auction turnover
ASSUMED_CLOSE_AUCTION_SHARE = 0.08       # auction turnover unknown -> 8% of the day's turnover (fill row liquidity_ref="assumed")
OPEN_CAP_PCT = 0.002                     # open fill <= 0.2% of the previous day's turnover
OPEN_SLIP_BPS = 5                        # open fills are worse than the print by 5 bps
ONE_SHARE_ROUNDUP = True                 # planned value < 1 share -> buy 1 share if it fits RISK's cap (min(MAX_POSITION_PCT*equity, free cash))
MIN_ORDER_KRW = 10_000.0                 # below this the order is ZERO (not filled)
MIN_ORDER_USD = 5.0

# ---- universe
KRX_MIN_MCAP_KRW = 3e11                  # ASSUMED 300bn KRW
KRX_MIN_AVG_TURNOVER_KRW = 5e9           # ASSUMED 5bn KRW/day (20-day average)
US_UNIVERSE = "SP500+NDX100"             # data/us_universe.json
EV_BAN_LOCKUP_DAYS = 5                   # no entry within +-5 trading days of a lock-up expiry
DEFAULT_SIZE_FRAC = 0.15                 # ASSUMED fixed fraction of equity per entry when a plugin has no size_frac

# ---- common RISK (risk.py). Plugins cannot override these (risk.PROTECTED_KEYS).
MAX_POSITION_PCT = 0.20                  # one position <= 20% of book equity at entry
DAILY_LOSS_LIMIT_PCT = 0.03              # book down >3% today -> no new entries today (no forced exits)
MAX_DRAWDOWN_HALT_PCT = 0.15             # book down >15% from peak -> halted (kv), user clears it
STALE_MAX_TRADING_DAYS = 1               # no mark for >1 trading day -> position flagged UNMEASURABLE
STALE_CLOSE_TRADING_DAYS = 3             # no mark for >3 trading days -> closed at the last price
HALT_FLAGS = ("거래정지", "관리종목", "투자위험", "정리매매", "상장폐지")        # RISK: 거래정지 = cannot fill -> HALTED; others -> sell next open
BAN_FLAGS = HALT_FLAGS + ("투자경고", "불성실공시", "단기과열")              # screen ban (availability TBC per source)

# ---- Toss Open API (QUOTES ONLY). Per-second group limits from openapi-docs/overview.md (2026-10-29) * 0.8.
TOSS_BASE = "https://openapi.tossinvest.com"
TOSS_RPS = {"AUTH": 4.0, "STOCK": 4.0, "STOCK_TRADING_TREND": 8.0, "MARKET_INFO": 2.4, "MARKET_DATA": 12.0,
            "MARKET_DATA_CHART": 16.0, "RANKING": 4.0}
TOSS_TOKEN_MARGIN_S = 60                 # refresh the token this long before it expires (one valid token per client)
TOSS_429_WAIT_S = 1.0                    # one retry after this wait on 429
KRX_UNIVERSE_TOP = 100                   # KRX universe = top N by 1-month trading amount (rankings) + held codes
KRX_UNIVERSE_TURNOVER_DAYS = 21          # ASSUMED trading days in the "1mo" ranking window (avg daily turnover = amount / 21)

# ---- public fallbacks (quotes.py). All TBC.
DART_BASE = "https://opendart.fss.or.kr/api"
ERAPI_FX = "https://open.er-api.com/v6/latest/USD"
STOOQ_DAILY = "https://stooq.com/q/d/l/?s={sym}.us&i=d"
FINNHUB_BASE = "https://finnhub.io/api/v1"

# ---- World Monitor (self-hosted only; regime_context reads its Redis). NEVER api.worldmonitor.app
WM_PORT = int(os.environ.get("WM_PORT", "3000"))
WM_BASE = f"http://localhost:{WM_PORT}"
