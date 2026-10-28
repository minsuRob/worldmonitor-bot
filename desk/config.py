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
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
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
RPC_RETRIES = 3
# ---- SIZE  (Kelly inputs below are ASSUMPTIONS, not estimates)
KELLY_CAP = 0.06                 # 6% of account, a ceiling not a target
MEME_ASSUMED_P_WIN = 0.45
MEME_ASSUMED_PAYOFF_B = 1.5
MIN_ORDER = 50.0
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
