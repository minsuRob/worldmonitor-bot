"""Fill and cost model: auction cap/partial, open slip/cap, limit touch, KRX/US costs, tick sizes, fractional qty, FX funding."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, done
import config as C
import fills as F

# ---- closing auction
f = F.fill_close_auction("KRX", 300_000, 10_000, auction_turnover=100_000_000)
check("auction fill at close, whole shares", f["status"] == "FILLED" and f["qty"] == 30 and f["price"] == 10_000 and f["liquidity_ref"] == "auction", f)
f = F.fill_close_auction("KRX", 300_000, 10_000, auction_turnover=10_000_000)      # cap 0.5% = 50,000 -> 5 shares
check("auction cap -> PARTIAL", f["status"] == "PARTIAL" and f["qty"] == 5 and f["partial"] == 1, f)
f = F.fill_close_auction("KRX", 300_000, 10_000, auction_turnover=None, day_turnover=1e10)
check("no auction turnover -> assumed share ref", f["liquidity_ref"] == "assumed" and f["qty"] == 30 and f["status"] == "FILLED", f)   # cap 1e10*0.08*0.005 = 4e6 >= 3e5
f = F.fill_close_auction("KRX", 300_000, 10_000, auction_turnover=None, day_turnover=1e8)                 # cap 4e4 -> 4 shares
check("assumed share cap -> PARTIAL", f["liquidity_ref"] == "assumed" and f["qty"] == 4 and f["status"] == "PARTIAL", f)
f = F.fill_close_auction("KRX", 150_000, 250_000, auction_turnover=1e9)
check("one share dearer than order -> ZERO with reason", f["status"] == "ZERO" and "one share" in f["detail"], f)
f = F.fill_close_auction("KRX", 5_000, 1_000, auction_turnover=1e9)
check("below MIN_ORDER_KRW -> ZERO", f["status"] == "ZERO" and "min order" in f["detail"], f)
check("no price -> NO_PRICE", F.fill_close_auction("KRX", 1e5, None)["status"] == "NO_PRICE")

# ---- open fills
f = F.fill_open("KRX", "BUY", 100_000, 10_000, prev_turnover=1e10)
check("open BUY slips up 5bps", abs(f["price"] - 10_005) < 1e-6 and f["qty"] == 9, f)                 # 100000/10005 = 9.99 -> 9
f = F.fill_open("KRX", "BUY", 100_000, 10_000, prev_turnover=1e6)                                        # cap 0.2% = 2,000 -> 0 shares
check("open cap tiny -> ZERO", f["status"] == "ZERO", f)
f = F.fill_open("KRX", "SELL", 9, 10_000)
check("open SELL slips down 5bps, always fills", f["status"] == "FILLED" and abs(f["price"] - 9_995) < 1e-6 and f["qty"] == 9, f)
check("SELL carries tax", f["tax"] > 0 and abs(f["tax"] - round(0.0020 * 9 * 9_995, 2)) < 0.01, f)

# ---- limit
check("limit BUY touched", F.fill_limit("KRX", "BUY", 100_000, 9_900, 9_850, 10_200)["status"] == "FILLED")
check("limit BUY not touched -> EXPIRED", F.fill_limit("KRX", "BUY", 100_000, 9_800, 9_850, 10_200)["status"] == "EXPIRED")
check("limit SELL touched", F.fill_limit("KRX", "SELL", 10, 10_100, 9_850, 10_200)["status"] == "FILLED")

# ---- costs
c = F.cost("KRX", "BUY", 1_000_000, 100)
check("KRX buy: fee only", c["fee"] == 150.0 and c["tax"] == 0.0 and c["other"] == 0.0, c)
c = F.cost("KRX", "SELL", 1_000_000, 100)
check("KRX sell: fee + 0.20% tax", c["fee"] == 150.0 and c["tax"] == 2000.0, c)
c = F.cost("KRX", "SELL", 1_000_000, 100, instrument="ETF")
check("KRX ETF sell: no tax", c["tax"] == 0.0, c)
c = F.cost("US", "SELL", 10_000, 50)
check("US sell: fee + SEC + TAF", abs(c["fee"] - 25.0) < 1e-9 and c["tax"] == 0.0 and abs(c["other"] - (0.0000278 * 10_000 + 0.000166 * 50)) < 1e-6, c)
c = F.cost("US", "BUY", 10_000, 50)
check("US buy: fee only", c["other"] == 0.0 and c["tax"] == 0.0)
# round trip on 1,000,000 KRW ~ 0.23%
rt = F.cost("KRX", "BUY", 1_000_000, 1)["fee"] + sum(F.cost("KRX", "SELL", 1_000_000, 1).values())
check("KRX round trip ~0.23%", abs(rt / 1_000_000 - 0.0023) < 1e-6, rt)

# ---- ticks and quantities
for px, want in ((1_999, 1_999), (2_004, 2_000), (19_995, 19_990), (49_999, 49_950), (199_999, 199_900), (499_999, 499_500), (1_234_567, 1_234_000)):
    check(f"tick {px}->{want}", F.round_tick_krx(px) == want, F.round_tick_krx(px))
check("KRX whole shares", F.round_qty("KRX", 3.9) == 3.0)
check("US fractional step", abs(F.round_qty("US", 0.123456) - 0.1234) < 1e-9)
C.US_FRACTIONAL = False
check("US whole when fractional off", F.round_qty("US", 2.7) == 2.0); C.US_FRACTIONAL = True

# ---- FX funding
usd, rate, cost_krw = F.fx_convert_once(1_000_000)
check("fx once: rate, cost", rate == C.FX_START_KRW_PER_USD and cost_krw == 1000.0 and abs(usd - 1_000_000 / 1400 * 0.999) < 1e-3, (usd, rate, cost_krw))
check("START_BALANCE_USD matches fx_convert_once", abs(C.START_BALANCE_USD - usd) < 1e-3)
done()
