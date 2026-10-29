"""Paper-only desk configuration. Values follow the user's reference guide
(lazyowen.com grok-bot-trading-team-setup). NO real orders, wallets, keys."""
import os
BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state")
LOGS = os.path.join(BASE, "logs")
DB = os.path.join(STATE, "desk.db")
SUMMARY = os.path.join(STATE, "summary.json")
ALERT_SNAPSHOT = os.path.join(STATE, "alert_snapshot.json")
REPORTS = os.path.join(STATE, "reports")
TZ = "Asia/Seoul"
UA = "paper-desk/0.1 (paper trading only; read-only public data)"

START_BALANCE = 1000.0           # USD, paper
WM_PORT = int(os.environ.get("WM_PORT", "3000"))
WM_BASE = f"http://localhost:{WM_PORT}"   # self-hosted only. NEVER api.worldmonitor.app
WM_CHECKS = {
    "fear_greed": "/api/market/v1/get-fear-greed-index",
    "prediction_markets": "/api/prediction/v1/list-prediction-markets?page_size=1",
    "cross_source_signals": "/api/intelligence/v1/list-cross-source-signals",
}
DEX = "https://api.dexscreener.com"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"   # kept for reference

def _load_env_file(path):
    """KEY=VALUE lines into os.environ (existing env wins). Desk .env is gitignored, mode 600."""
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
_load_env_file(os.path.join(BASE, ".env"))
HELIUS_KEY_FILE = "/workspace/secrets/helius_api_key.txt"
if not os.environ.get("HELIUS_API_KEY"):
    try: os.environ["HELIUS_API_KEY"] = open(HELIUS_KEY_FILE).read().strip()
    except OSError: pass
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "").strip()   # read-only RPC key. NEVER log/print it.
HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY else None
# Read-only RPC list, tried in order: optional SOLANA_RPC_URL, then Helius (keyed, free plan), then public RPCs.
# RugCheck stays the last fallback for top holders. Never a wallet, never a send.
SOLANA_RPCS = ([os.environ["SOLANA_RPC_URL"]] if os.environ.get("SOLANA_RPC_URL") else []) + \
    ([HELIUS_RPC] if HELIUS_RPC else []) + [
    "https://api.mainnet-beta.solana.com",
    "https://api.mainnet.solana.com",
    "https://solana.leorpc.com/?api_key=FREE",
]
HELIUS_RPS = 8.0                 # free plan: 10 req/s standard RPC; stay under it
HELIUS_DAS_RPS = 2.0             # free plan DAS (getTokenAccounts) limit is lower: 2 req/s
HOLDER_COUNT_PAGE = 1000         # DAS getTokenAccounts page size (10 credits per page)
HOLDER_COUNT_MAX_PAGES = 5       # cap: <=50 credits per token; more -> count is a lower bound ("capped")
HELIUS_DAS_DAILY_CREDITS = 20_000   # DAS budget/day (~600k/month of the 1M free); over it -> holder count skipped
# No-key fallback for top holders when every RPC blocks getTokenLargestAccounts (public mainnet does: 429).
RUGCHECK = "https://api.rugcheck.xyz/v1"
GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://external-api.kalshi.com/trade-api/v2"

# ---- SCAN
SCAN_INTERVAL_S = 900            # guide: every 15 minutes
SCAN_MIN_LIQ = 10_000.0
SCAN_MAX = 10
SCAN_DEDUP_MIN = 60
# ---- VET
VET_TOP_HOLDER_MAX = 0.05
VET_MIN_LIQ = 10_000.0
VET_LIQ_MULT = 50.0
VET_H1_ALREADY_PRICED = 25.0     # % priceChange.h1 above which the signal is "already priced"
VET_MIN_AGE_MIN = 30
VET_MIN_REJECTS_PER_DAY = 10
RPC_RETRIES = 3                  # per endpoint, exponential backoff 1s,2s,4s (429 -> next endpoint)
RPC_BACKOFF_S = 1.0
RUGCHECK_RETRIES = 3
RPC_BLOCK_COOLDOWN_S = 600        # skip RPC holder lookup 10 min after all endpoints refused it
# check 3 "price up while holders flat": compare with this token's earlier holder snapshot (Helius DAS count)
HOLDER_SNAPSHOTS = os.path.join(STATE, "holder_snapshots.db")
VET_HOLDER_SNAPSHOT_MIN_AGE_MIN = 30   # earlier snapshot must be at least this old
VET_HOLDER_SNAPSHOT_MAX_AGE_H = 24
VET_PRICE_UP_PCT = 5.0          # price up >= 5% since that snapshot ...
VET_HOLDERS_FLAT_PCT = 1.0      # ... while holder count grew < 1% -> REJECT 3_price_vs_holders
# ---- SIZE  (Kelly inputs below are ASSUMPTIONS, not estimates)
KELLY_CAP = 0.06                 # 6% of account, a ceiling not a target
MEME_ASSUMED_P_WIN = 0.45
MEME_ASSUMED_PAYOFF_B = 1.5
MIN_ORDER = 30.0
SLIPPAGE_BUDGET = 0.02
ADD_TRIGGER_GAIN = 0.50          # one add only after confirmed +50% ...
ADD_PULLBACK = 0.10              # ... and a >=10% pullback from the peak (still above entry)
# ---- FILLS
FEE_RATE = 0.0045
FEE_MIN = 0.95
FEE_FLOOR_MAX_EFFECTIVE = 0.02   # effective fee above 2% -> FEE_FLOOR
SLIPPAGE_LIMIT = 0.02
# ---- BOOK
BOOK_INTERVAL_S = 900
BOOK_CATEGORIES = ["crypto"]
BOOK_MIN_EDGE = 0.08
BOOK_MAX_OPEN = 7
BOOK_MAX_DATA_AGE_H = 48
# ---- RISK
RISK_INTERVAL_S = 300            # every 5 minutes, own timer
RISK_VOL_RATIO_MIN = 0.20
RISK_RETRIES = 2
RISK_FLAG_MCAP_GAIN = 0.60
# ---- CHIEF
HEARTBEAT_STALE_S = 90
SUPERVISE_EVERY_S = 30
CHECKS_EVERY_S = 60
DEATHS_PER_HOUR_HALT = 2
CLOSE_REPORT_HOUR = 23           # KST
ALERT_MOVE = 0.10
BOTS = ["scan", "vet", "book", "size", "fills", "risk"]
# ---- per-book variant knobs (unset for the desk; set only inside manual/run_variants.rules(v) for books C/D)
SIZE_FIXED_FRACTION = None       # fixed fraction of equity instead of the capped assumed-Kelly
MAX_OPEN_POSITIONS = None        # cap on concurrent meme positions + pending entries
