"""Korean close report, built only from real state in desk.db. Usage: python3 report.py [YYYY-MM-DD]"""
import sys, json
import config as C
from common import *

def main():
    c = init_db()
    day = sys.argv[1] if len(sys.argv) > 1 else kst_day()
    ds, de = day_start_ts(day), day_start_ts(day) + 86400
    a = c.execute("SELECT * FROM account WHERE id=1").fetchone()
    rows, mv, unreal = mark_positions(c)
    realized_day = c.execute("SELECT COALESCE(SUM(realized_pnl),0) s FROM positions WHERE status='CLOSED' AND closed_ts>=? AND closed_ts<?", (ds, de)).fetchone()["s"]
    realized_all = c.execute("SELECT COALESCE(SUM(realized_pnl),0) s FROM positions WHERE status='CLOSED'").fetchone()["s"]
    deployed = c.execute("SELECT COALESCE(SUM(cost_usd),0) s FROM positions").fetchone()["s"]
    eq0 = c.execute("SELECT equity FROM equity WHERE ts>=? ORDER BY ts LIMIT 1", (ds,)).fetchone()
    start_bal = eq0["equity"] if eq0 else a["start_balance"]
    equity = a["cash"] + mv
    total = realized_all + unreal
    P = print
    P(f"[모의 매매 데스크 마감 보고] {day} (작성 {kst_str()})")
    P("※ 모의 매매입니다. 실제 주문·지갑·거래소 연결 없음.")
    s = json.load(open(C.SUMMARY)) if os.path.exists(C.SUMMARY) else {}
    P(f"상태: READY={s.get('READY')} / degraded={s.get('degraded')} {('('+s['degraded_reason']+')') if s.get('degraded_reason') else ''} / halted={s.get('halted')}")
    P("")
    P(f"1) 잔고: 시작 ${start_bal:,.2f} (최초 ${a['start_balance']:,.2f}) → 마감 ${equity:,.2f} (현금 ${a['cash']:,.2f} + 평가 ${mv:,.2f})")
    pct = f"{total/deployed*100:+.2f}%" if deployed else "투입 자본 없음(0%)"
    P(f"   손익: 실현 ${realized_all:+,.2f} (오늘 ${realized_day:+,.2f}) / 미실현 ${unreal:+,.2f} / 합계 ${total:+,.2f} = 실제 투입 자본 ${deployed:,.2f} 대비 {pct}")
    P("")
    cands = c.execute("SELECT * FROM candidates WHERE ts>=? AND ts<? ORDER BY ts", (ds, de)).fetchall()
    drops = c.execute("SELECT reason, COUNT(*) n FROM scan_drops WHERE ts>=? AND ts<? GROUP BY reason", (ds, de)).fetchall()
    P(f"2) 후보 (SCAN {len(cands)}개, SCAN 단계 제외 {sum(d['n'] for d in drops)}개)")
    for d in drops: P(f"   - SCAN 제외: {d['reason'][:60]} ×{d['n']}")
    for r in cands:
        res = r["vet_result"] or "대기"
        why = f" / 거절 검사: {r['vet_check']} — {r['vet_detail']}" if r["vet_result"] == "REJECT" else (f" / {r['vet_detail']}" if r["vet_detail"] else "")
        P(f"   - {r['symbol']} ({r['token'][:8]}…) 유동성 ${r['liquidity']:,.0f} 점수 {r['score']:.2f} → VET {res}{why}")
    rej = sum(1 for r in cands if r["vet_result"] == "REJECT")
    if rej < C.VET_MIN_REJECTS_PER_DAY: P(f"   ⚠ 오늘 VET 거절 {rej}건 (<{C.VET_MIN_REJECTS_PER_DAY}건): 검사가 너무 느슨하거나 후보가 적음")
    P("")
    bets = c.execute("SELECT * FROM bets WHERE ts>=? AND ts<?", (ds, de)).fetchall()
    P(f"3) 예측시장 베팅 ({len(bets)}건)")
    for b in bets: P(f"   - {b['title'][:60]} {b['side']} 내 확률 {b['model_prob']:.3f} vs 시장 {b['market_price']:.3f} (엣지 {b['edge']:+.3f}) [{b['status']}]")
    nb = c.execute("SELECT detail, COUNT(*) n FROM events WHERE bot='book' AND ts>=? AND ts<? GROUP BY detail", (ds, de)).fetchall()
    for e in nb: P(f"   - BOOK: {e['detail'][:100]} ×{e['n']}")
    if not bets and not nb: P("   - BOOK 휴식 (World Monitor degraded) 또는 기록 없음")
    P("")
    orders = c.execute("SELECT * FROM orders WHERE ts>=? AND ts<?", (ds, de)).fetchall()
    P(f"4) SIZE (Kelly 상한 {C.KELLY_CAP*100:.0f}%, 최소 주문 ${C.MIN_ORDER:.0f})")
    for o in orders: P(f"   - {o['kind']} {o['symbol']}: Kelly {o['kelly_raw']*100:.1f}% → 상한적용 {o['kelly_capped']*100:.1f}% → ${o['dollars']:.2f} [{o['status']}] {o['reason'] or ''} {o['detail'] or ''}")
    if not orders: P("   - 없음")
    P("")
    fills = c.execute("SELECT * FROM fills WHERE ts>=? AND ts<?", (ds, de)).fetchall()
    P("5) 체결 및 슬리피지")
    for f in fills:
        P(f"   - {f['action']} {f['symbol']} ${f['filled_usd']:.4f}/{f['requested_usd']:.4f}{' (부분체결)' if f['partial'] else ''} 예상 {f['expected_price']:.10g} → 체결 {f['fill_price']:.10g} 슬리피지 {f['slippage_bps']:.1f}bp 수수료 ${f['fee']:.2f}{' ⚠ 2% 한도 초과' if f['over_limit'] else ''}")
    if not fills: P("   - 없음")
    P("")
    closed = c.execute("SELECT * FROM positions WHERE status='CLOSED' AND closed_ts>=? AND closed_ts<?", (ds, de)).fetchall()
    P("6) 청산 (RISK 결정, 최종)")
    for p in closed: P(f"   - {p['symbol']}: 규칙 {p['close_rule']} ({p['close_detail']}) 손익 ${p['realized_pnl']:+.2f}")
    if not closed: P("   - 없음")
    P(f"   보유 중: {len(rows)}개")
    for r in rows: P(f"   - {r['symbol']} 원가 ${r['cost_usd']:.2f} 평가 ${(r['qty'] or 0)*(r['last_price'] or r['entry_price']):.2f}")

if __name__ == "__main__":
    main()
