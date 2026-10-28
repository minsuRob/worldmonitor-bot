"""Prints a short Korean alert ONLY if equity, total PnL, or any open position moved >10% since the last alerted snapshot;
then updates the snapshot. Prints nothing otherwise."""
import json, os
import config as C
from common import now, kst_str

def pct(a, b):
    if b is None or a is None: return None
    if b == 0: return None if a == 0 else float("inf")
    return (a - b) / abs(b)

def main():
    if not os.path.exists(C.SUMMARY): return
    s = json.load(open(C.SUMMARY))
    cur = {"ts": s["updated"], "equity": s["equity"], "total_pnl": s["total_pnl"],
           "positions": {str(p["id"]): {"symbol": p["symbol"], "value_usd": p["value_usd"]} for p in s["open_positions"]}}
    if not os.path.exists(C.ALERT_SNAPSHOT):
        json.dump(cur, open(C.ALERT_SNAPSHOT, "w"), ensure_ascii=False); return
    snap = json.load(open(C.ALERT_SNAPSHOT))
    msgs = []
    d = pct(cur["equity"], snap.get("equity"))
    if d is not None and abs(d) > C.ALERT_MOVE: msgs.append(f"자산 ${snap['equity']:.2f}→${cur['equity']:.2f} ({d*100:+.1f}%)")
    d = pct(cur["total_pnl"], snap.get("total_pnl"))
    if d is not None and abs(d) > C.ALERT_MOVE and abs(cur["total_pnl"] - (snap.get("total_pnl") or 0)) >= 0.01:
        msgs.append(f"총손익 ${snap.get('total_pnl',0):+.2f}→${cur['total_pnl']:+.2f}")
    for pid, p in cur["positions"].items():
        old = (snap.get("positions") or {}).get(pid)
        if old:
            d = pct(p["value_usd"], old["value_usd"])
            if d is not None and abs(d) > C.ALERT_MOVE: msgs.append(f"{p['symbol']} ${old['value_usd']:.2f}→${p['value_usd']:.2f} ({d*100:+.1f}%)")
    if msgs:
        print(f"[모의데스크 알림 {kst_str()}] " + " / ".join(msgs))
        json.dump(cur, open(C.ALERT_SNAPSHOT, "w"), ensure_ascii=False)

if __name__ == "__main__":
    main()
