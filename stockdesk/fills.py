"""PAPER fill and cost model for stocks (KRX whole shares, US fractional). No AMM impact model.

Fills happen at exchange prints (close / open / limit touched) with a liquidity cap and, for opens, a small
adverse slip. Every assumption is a config.py constant marked ASSUMED. Returns plain dicts so run.py can write
one `fills` row per call.
"""
import math
import config as C

def round_tick_krx(px):
    """KRX tick size (2023-01 revision, KOSPI/KOSDAQ common). Used for limit prices only."""
    if px < 2_000: t = 1
    elif px < 5_000: t = 5
    elif px < 20_000: t = 10
    elif px < 50_000: t = 50
    elif px < 200_000: t = 100
    elif px < 500_000: t = 500
    else: t = 1_000
    return math.floor(px / t) * t

def round_qty(market, qty):
    if market == "KRX": return float(math.floor(qty))
    if not C.US_FRACTIONAL: return float(math.floor(qty))
    return math.floor(qty / C.US_QTY_STEP) * C.US_QTY_STEP

def min_order(market): return C.MIN_ORDER_KRW if market == "KRX" else C.MIN_ORDER_USD

def cost(market, side, value, qty, instrument="STOCK"):
    """{'fee','tax','other'} in the market currency. KRX: fee both sides + sell tax (ETF exempt). US: fee + SEC/TAF on sells."""
    if market == "KRX":
        fee = C.KRX_FEE_RATE * value
        tax = C.KRX_TAX_SELL.get(instrument if instrument in C.KRX_TAX_SELL else "KOSPI", C.KRX_TAX_SELL["KOSPI"]) * value if side == "SELL" else 0.0
        return {"fee": round(fee, 2), "tax": round(tax, 2), "other": 0.0}
    fee = C.US_FEE_RATE * value
    other = 0.0
    if side == "SELL":
        other = C.US_SEC_FEE_SELL * value + min(C.US_FINRA_TAF_PER_SHARE * qty, C.US_FINRA_TAF_MAX)
    return {"fee": round(fee, 4), "tax": 0.0, "other": round(other, 4)}

def _fill(market, value_req, px, cap_value, liquidity_ref, side="BUY", instrument="STOCK", one_share_max=None):
    """Shared: cap by liquidity, round qty, apply costs. value_req in market currency.
    one_share_max: when the planned value buys 0 whole shares, buy ONE share if it costs <= one_share_max (the caller passes
    RISK's limit: min(MAX_POSITION_PCT * equity, free cash)) and <= the liquidity cap. Small books can then hold dear stocks."""
    if px is None or px <= 0: return {"status": "NO_PRICE", "qty": 0.0, "value": 0.0}
    want = value_req if cap_value is None else min(value_req, cap_value)
    qty = round_qty(market, want / px)
    rounded_up = False
    if qty <= 0 and C.ONE_SHARE_ROUNDUP and one_share_max and px <= one_share_max and (cap_value is None or px <= cap_value):
        qty, rounded_up = 1.0, True
    value = qty * px
    if qty <= 0 or value < min_order(market):
        why = (f"one share ({px:,.0f}) costs more than the allowed value {want:,.0f}" if qty <= 0 else f"{value:,.0f} below min order {min_order(market):,.0f}")
        return {"status": "ZERO", "qty": 0.0, "value": 0.0, "price": px, "partial": 0, "liquidity_ref": liquidity_ref,
                "fee": 0.0, "tax": 0.0, "other": 0.0, "detail": f"{why} (requested {value_req:,.0f}, cap {cap_value if cap_value is not None else 'none'})"}
    cst = cost(market, side, value, qty, instrument)
    partial = 1 if (not rounded_up and cap_value is not None and cap_value < value_req) else 0   # share rounding alone is not a partial fill
    return {"status": "PARTIAL" if partial else "FILLED", "qty": qty, "value": round(value, 4), "price": px, "partial": partial,
            "liquidity_ref": liquidity_ref, **cst,
            "detail": f"cap={cap_value if cap_value is not None else 'none'}" + (f"; rounded up to 1 share (planned {value_req:,.0f})" if rounded_up else "")}

def fill_close_auction(market, value_req, close_px, auction_turnover=None, day_turnover=None, instrument="STOCK", one_share_max=None):
    """KRX closing auction: fill at the close, <= CB_AUCTION_CAP_PCT of the auction turnover.
    Auction turnover unknown -> ASSUMED share of the day's turnover (liquidity_ref='assumed')."""
    if auction_turnover:
        cap, ref = C.CB_AUCTION_CAP_PCT * auction_turnover, "auction"
    elif day_turnover:
        cap, ref = C.CB_AUCTION_CAP_PCT * day_turnover * C.ASSUMED_CLOSE_AUCTION_SHARE, "assumed"
    else:
        cap, ref = None, "none"
    return _fill(market, value_req, close_px, cap, ref, "BUY", instrument, one_share_max)

def fill_open(market, side, value_req_or_qty, open_px, prev_turnover=None, instrument="STOCK", one_share_max=None):
    """Open print with OPEN_SLIP_BPS adverse slip. BUY: value_req, capped by OPEN_CAP_PCT * previous turnover.
    SELL: qty (whole position), no cap (exits always fill, the price just slips)."""
    if open_px is None or open_px <= 0: return {"status": "NO_PRICE", "qty": 0.0, "value": 0.0}
    slip = open_px * C.OPEN_SLIP_BPS / 10_000
    if side == "BUY":
        px = open_px + slip
        cap = C.OPEN_CAP_PCT * prev_turnover if prev_turnover else None
        return _fill(market, value_req_or_qty, px, cap, "prev_turnover" if cap is not None else "none", "BUY", instrument, one_share_max)
    px = max(open_px - slip, 0.0)
    qty = value_req_or_qty; value = qty * px
    cst = cost(market, "SELL", value, qty, instrument)
    return {"status": "FILLED", "qty": qty, "value": round(value, 4), "price": px, "partial": 0, "liquidity_ref": "open", **cst, "detail": "sell at open"}

def fill_at_price(market, side, qty, px, instrument="STOCK", ref="mark"):
    """Exit at a given print (RISK close at last price, stop hit at the day's price). No slip."""
    value = qty * px
    cst = cost(market, side, value, qty, instrument)
    return {"status": "FILLED", "qty": qty, "value": round(value, 4), "price": px, "partial": 0, "liquidity_ref": ref, **cst, "detail": f"{side} at {ref}"}

def fill_limit(market, side, qty_or_value, limit_px, day_low, day_high, instrument="STOCK"):
    """Limit order fills at the limit if the day's range touched it; otherwise not filled (EXPIRED)."""
    if day_low is None or day_high is None: return {"status": "NO_PRICE", "qty": 0.0, "value": 0.0}
    touched = (day_low <= limit_px) if side == "BUY" else (day_high >= limit_px)
    if not touched: return {"status": "EXPIRED", "qty": 0.0, "value": 0.0, "price": limit_px, "partial": 0, "liquidity_ref": "range", "fee": 0.0, "tax": 0.0, "other": 0.0, "detail": "limit not touched"}
    if side == "BUY": return _fill(market, qty_or_value, limit_px, None, "limit", "BUY", instrument)
    return fill_at_price(market, "SELL", qty_or_value, limit_px, instrument, "limit")

def fx_convert_once(krw, rate=None):
    """Fund a USD book once from KRW at `rate` (default config FX_START) minus FX_CONVERSION_COST. Returns (usd, rate, cost_krw)."""
    rate = rate or C.FX_START_KRW_PER_USD
    gross = krw / rate
    cost_krw = krw * C.FX_CONVERSION_COST
    return round(gross * (1 - C.FX_CONVERSION_COST), 4), rate, round(cost_krw, 2)
