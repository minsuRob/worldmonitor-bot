# 데스크 봇과 CHIEF

[← 인덱스](../../CLAUDE.md) · 코드: `desk/bots.py`, `desk/chief.py`, 값: `desk/config.py` · 원 가이드 요약: [guide-params](../guide-params.md)

## 파이프라인: SCAN → VET → BOOK → SIZE → FILLS → RISK
| 봇 | 하는 일 | 핵심 값 (`config.py`) |
|---|---|---|
| SCAN | DexScreener에서 후보 수집, 유동성·매도 우세 제외, 최근 본 토큰 중복 제거 | `SCAN_INTERVAL_S=900`, `SCAN_MIN_LIQ=10000`, `SCAN_MAX=10`, `SCAN_DEDUP_MIN=60` |
| VET | 7개 검사를 순서대로, 첫 거절에서 멈춤 → `PASS` / `PASS_PARTIAL` / `REJECT` | 아래 표 |
| BOOK | 예측시장(WM 목록 + Kalshi/Polymarket 가격). 엣지 >8%만, 최대 7개 | `BOOK_MIN_EDGE=0.08`, `BOOK_MAX_OPEN=7` |
| SIZE | Kelly(가정값) 6% 상한, 묶이지 않은 현금, 유동성/50, 슬리피지 예산으로 제한 | `KELLY_CAP=0.06`, `MIN_ORDER=30`, `SLIPPAGE_BUDGET=0.02` |
| FILLS | 상수곱 AMM 체결 모델, 수수료 max(0.45%, $0.95), 2% 넘는 슬리피지 표시 | `FEE_RATE`, `FEE_MIN`, `SLIPPAGE_LIMIT` |
| RISK | 자체 타이머, 최종 권한. 거래량 붕괴·측정 불가 청산, +60% 시총 표시 | `RISK_INTERVAL_S=300`, `RISK_VOL_RATIO_MIN=0.20` |

- 밈코인 Kelly 입력값은 **가정**이다: `MEME_ASSUMED_P_WIN=0.45`, `MEME_ASSUMED_PAYOFF_B=1.5`. 추정치가 아니다.
- 15분 장부 사이클에서는 BOOK(예측시장)을 쓰지 않는다. 밈코인만 다룬다.

## VET 7개 검사 (`bots.vet_one`)
| 순서 | 코드 | 거절 조건 (BASE 값) |
|---|---|---|
| 1 | `1_top_holder` | 최대 보유자 > `VET_TOP_HOLDER_MAX`(5%), 또는 조회 실패 |
| 2 | `2_liquidity` | 유동성 < `VET_MIN_LIQ`($10k) 또는 주문의 50배 미만 |
| 3 | `3_price_vs_holders` | 이전 스냅샷 대비 가격 +5% 이상인데 보유자 증가 <1% (Helius DAS). 비교 불가면 `PASS_PARTIAL` |
| 4 | `4_already_in_h1` | `priceChange.h1` ≥ `VET_H1_ALREADY_PRICED`(25%) |
| 5 | (없음) | 단일 출처 뉴스 검사. 스캔 후보는 뉴스 기반이 아니라 건너뜀 |
| 6 | `6_no_edge_after_fees` | 가정 엣지 − 왕복 비용 ≤ 0, 또는 계획 주문 0 |
| 7 | `7_young_shrinking_liq` | 30분 미만 페어인데 유동성이 줄었거나 다시 측정 불가 |

장부별 추가 검사(C/D 사전 검사, D 사후 검사·run30)는 [paper-books.md](paper-books.md), 코드 목록은 [glossary.md](glossary.md).

## 공통 RISK (`bots.risk_cycle`) — 모든 장부 동일, 아무도 뒤집지 않음
| 규칙 | 조건 | 동작 |
|---|---|---|
| `UNMEASURABLE` | 2회 재시도 후에도 가격 측정 실패 | 마지막 측정가로 청산 |
| `VOL_RATIO<0.20` | `volume.h6 / (volume.h24/4) < 0.20` | 전량 청산 |
| `FLAG_MCAP_+60` | 시총 ≥ 진입 시총 × 1.6 | **표시만**, 팔지 않음 |

손절·익절·추적 손절은 공통 RISK에 없다. C·D 장부만 RISK 뒤에 자기 매도를 추가한다.

## CHIEF 감독 규칙 (`chief.py`, 사용자 지정)
- CHIEF는 포지션을 열거나, 크기를 정하거나, 닫지 않는다. RISK를 뒤집지 않는다.
- VET를 통과하지 않은 것은 SIZE로 가지 않는다.
- 봇이 응답을 2번 놓치면(하트비트 90초 초과 또는 프로세스 종료) 1번 재시작하고 기록한다.
- 같은 봇이 1시간에 2번 죽으면 데스크를 **중단**한다(`halted`). 아무것도 닫지 않고, RISK는 계속 돈다.
- World Monitor 체크가 비었거나 오류면 `degraded`, BOOK은 쉰다. 밈코인은 DexScreener로 계속.
- **READY**는 WM 체크 3개가 모두 실제 데이터 + DexScreener 정상 + 6개 봇 하트비트 정상 + 중단 아님일 때만. `api.worldmonitor.app`으로 넘어가지 않는다.
- 매일 23:00 KST 마감 보고(`report.py`), 10% 넘는 변동만 알림(`check_alert.py`).

## 상시 데스크 실행 (현재 미가동)
```bash
cd desk && WM_PORT=3000 ./start.sh   # CHIEF가 6개 봇 실행
./stop.sh                            # 포지션을 닫지 않음
```
상태 `desk/state/summary.json`, 로그 `desk/logs/supervisor.log`.
