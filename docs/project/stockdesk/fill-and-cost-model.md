# 체결·비용 모델 (모의)

[← 인덱스](../../../CLAUDE.md) · 코드: `stockdesk/fills.py`, 값은 `stockdesk/config.py`(`# ---- costs`, `# ---- fill model`), 호출은 `stockdesk/run.py`(`_fill_pending`, `_exits`), `stockdesk/risk.py`(`close_position`)

체결은 거래소 체결가(종가·시초가·지정가 접촉)에서 일어나고 유동성 상한과, 시초가에는 작은 불리한 슬립이 붙는다. AMM 충격 모델(코인 데스크)은 없다. 모든 가정값은 `config.py`에 `ASSUMED`로 표시돼 있다.

## 함수별 규칙 (`fills.py`)
| 함수 | 쓰는 곳 | 가격 | 상한(`liquidity_ref`) | 결과 상태 |
|---|---|---|---|---|
| `fill_close_auction(market, value_req, close_px, auction_turnover, day_turnover)` | CB 주문(`CLOSE_AUCTION`), `krx_close` 슬롯 | 종가(스냅 `price`) | 동시호가 거래대금 × `CB_AUCTION_CAP_PCT` 0.5%(`auction`); 동시호가 거래대금이 없으면 당일 거래대금 × `ASSUMED_CLOSE_AUCTION_SHARE` 8% × 0.5%(`assumed`); 둘 다 없으면 상한 없음(`none`) | FILLED / PARTIAL / ZERO / NO_PRICE |
| `fill_open(market, "BUY", value_req, open_px, prev_turnover)` | `OPEN_NEXT` 주문, `krx_open`/`us_open` | 시초가 + `OPEN_SLIP_BPS` 5bps | 전일 거래대금 × `OPEN_CAP_PCT` 0.2%(`prev_turnover`), 전일 거래대금 없으면 상한 없음 | FILLED / PARTIAL / ZERO / NO_PRICE |
| `fill_open(market, "SELL", qty, open_px)` | (정의만; 실제 시초가 매도는 `run._exits`가 `open_px × (1 − 5bps)`로 `risk.close_position` 호출) | 시초가 − 5bps | 없음(매도는 항상 전량 체결) | FILLED |
| `fill_at_price(market, side, qty, px, ref)` | RISK 청산(`UNMEASURABLE_CLOSE` 마지막 가격, `FLAG_…` 슬롯 가격), 장부별 매도(시초가 슬롯이 아니면 `mark`) | 주어진 가격, 슬립 없음 | 없음 | FILLED |
| `fill_limit(market, side, qty_or_value, limit_px, day_low, day_high)` | `LIMIT` 주문(현재 쓰는 전략 없음) | 지정가. 매수는 당일 저가 ≤ 지정가, 매도는 고가 ≥ 지정가일 때 | 없음(`limit`) | FILLED / EXPIRED / NO_PRICE |
| `round_tick_krx(px)` | 지정가용(현재 호출 없음) | 호가단위로 내림 | — | — |
| `round_qty(market, qty)` | 모든 매수 | KRX 정수주 내림, US `US_QTY_STEP` 0.0001주 내림(`US_FRACTIONAL=True`) | — | — |
| `cost(market, side, value, qty, instrument)` | 모든 체결·청산 | 아래 비용 표 | — | `{fee, tax, other}` |
| `fx_convert_once(krw, rate)` | USD 장부 개설 1회(`run.vdb`) | `krw / rate × (1 − FX_CONVERSION_COST)` | — | `(usd, rate, cost_krw)` |

- `_fill`(공통): `want = min(value_req, cap)` → 수량 내림 → `value = qty × px`. `qty ≤ 0`이거나 `value < 최소 주문`이면 **ZERO**(사유: "1주가 허용 금액보다 비쌈" 또는 "최소 주문 미달"). 상한이 요청 금액보다 작아 깎였으면 **PARTIAL**(`partial=1`), 수량 내림만으로 줄어든 것은 PARTIAL이 아니다.
- `NO_PRICE`·`EXPIRED`·`ZERO`면 주문은 그 상태로 끝나고 다시 시도하지 않는다(`run._fill_pending`). 체결되면 포지션 `cost = value + fee + tax + other`, 현금에서 그만큼 뺀다. 청산 `proceeds = value − 비용`, `realized_pnl = proceeds − cost`.

## 비용 표 (`config.py`)
| 시장 | 항목 | 값 | 비고 |
|---|---|---|---|
| KRX | 수수료 `KRX_FEE_RATE` | 0.015% × 매수·매도 각각 | 사용자 지정(이벤트 계좌는 더 낮을 수 있음) |
| KRX | 거래세 `KRX_TAX_SELL` | 매도 시 KOSPI 0.20%, KOSDAQ 0.20%, **ETF 0%** | 사용자 지정 0.20%; **TBC: 해당 연도 법정 요율**. `instrument`가 `KOSPI`/`KOSDAQ`/`ETF`가 아니면(`STOCK`) KOSPI 요율 적용 |
| US | 수수료 `US_FEE_RATE` | 0.25% × 매수·매도 각각 | 계좌에 따라 0.07~0.25% |
| US | SEC 수수료 `US_SEC_FEE_SELL` | 매도 시 0.00278% | TBC(Section 31, 매년 변동) |
| US | FINRA TAF `US_FINRA_TAF_PER_SHARE` / `_MAX` | 매도 시 주당 $0.000166, 최대 $8.30 | TBC |
| 공통 | EV 규칙용 왕복 비용 `ROUNDTRIP_COST` | KRX 0.006, US 0.0055 | 수수료 + 세금 + ASSUMED 충격. `buy_mode=ev`의 EV 식에서만 쓴다(체결 비용과 별도) |

KRX 왕복(매수+매도) 실제 비용 = 0.015% + 0.015% + 0.20% = **0.23%**(ETF 0.03%).

## 호가단위 (`round_tick_krx`, 2023-01 개정, KOSPI·KOSDAQ 공통)
| 가격 | <2,000 | <5,000 | <20,000 | <50,000 | <200,000 | <500,000 | ≥500,000 |
|---|---|---|---|---|---|---|---|
| 단위 | 1 | 5 | 10 | 50 | 100 | 500 | 1,000 |

지정가에만 쓰며, 시장가 체결(종가·시초가)에는 적용하지 않는다.

## 정수주 / 소수주
- KRX: 정수주만(`math.floor`). **₩1,000,000 시드에서 1주 가격이 허용 금액(잔고의 20% = 약 20만 원, CB는 30%여도 RISK 상한 20%)을 넘는 고가 종목은 `ZERO`**로 체결되지 않는다. 이 사유는 `orders.reason`에 "one share (…) costs more than the allowed value …"로 남는다.
- US: `US_FRACTIONAL=True`, `US_QTY_STEP` 0.0001주 단위 내림(토스가 소수 수량 "0.5" 지원). 최소 주문 $5.

## FX: 1회 환전
- USD 장부(ER-US·MO-US)는 개설 때 한 번만 환전한다: `START_BALANCE_USD = START_BALANCE_KRW / FX_START_KRW_PER_USD × (1 − FX_CONVERSION_COST)` = 1,000,000 / 1400 × 0.999 ≈ **$713.57**. 1400은 ASSUMED, 0.1%는 ASSUMED. 쓴 값은 `kv.fx_start`와 `fills`의 `FX_FUND` 행(`other_fee` = 환전 비용 ₩1,000)에 기록된다.
- 이후 환전은 없다. 매매는 USD로만 하고, **보고서의 KRW 환산**에만 매일 환율(`market.db.fx_daily`, 출처 toss → erapi → 없으면 config 1400)을 쓴다.
- 보고서(`report.py`): `ret%ccy` = USD 기준 수익률, `ret%KRW` = `equity × 최신 fx_daily / 1,000,000 − 1`, `fx%` = `ret%KRW − ret%ccy`(환율 효과). `equity` 테이블의 EOD 행에 `fx_rate`, `fx_source`, `equity_krw`가 함께 저장되고 `--series`는 모든 장부를 KRW 기준으로 정렬한다.

## 가정값 목록 (`config.py`, 모두 ASSUMED)
| 상수 | 값 | 의미 |
|---|---|---|
| `CB_AUCTION_CAP_PCT` | 0.005 | 동시호가 체결 ≤ 동시호가 거래대금의 0.5% |
| `ASSUMED_CLOSE_AUCTION_SHARE` | 0.08 | 동시호가 거래대금을 모르면 당일 거래대금의 8%로 가정(`liquidity_ref="assumed"`) |
| `OPEN_CAP_PCT` | 0.002 | 시초가 체결 ≤ 전일 거래대금의 0.2% |
| `OPEN_SLIP_BPS` | 5 | 시초가 체결은 체결가보다 5bps 불리(매수 +, 매도 −) |
| `MIN_ORDER_KRW` / `MIN_ORDER_USD` | 10,000 / 5 | 미달이면 ZERO |
| `FX_START_KRW_PER_USD` / `FX_CONVERSION_COST` | 1400 / 0.001 | 1회 환전 |
| `DEFAULT_SIZE_FRAC` | 0.15 | `size_frac`이 없는 전략의 진입 비율 |
| `KRX_MIN_MCAP_KRW` / `KRX_MIN_AVG_TURNOVER_KRW` | 3e11 / 5e9 | 유니버스 필터(시총 3000억, 20일 평균 거래대금 50억) |

토스 API에는 동시호가 거래대금이 없어(공식 스펙, 2026-10-29 확인) 실데이터에서 `auction_turnover`는 항상 비어 있고, CB 체결은 항상 `assumed` 경로다(→ [data-sources.md](data-sources.md#토스에-없는-것)). 일봉 거래대금도 토스에 없어 `prev_turnover`는 전일 종가 × 거래량이다. 테스트: `manual/tests/test_fills_costs.py` → [testing.md](testing.md)
