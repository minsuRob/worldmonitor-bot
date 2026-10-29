# 슬롯 스케줄

[← 인덱스](../../../CLAUDE.md) · 코드: `stockdesk/schedule.py`(`SLOTS`, `due`, 거래일), `stockdesk/run.py`(`due`, `run_slot`), `stockdesk/marketdb.py`(`slot_runs`), `stockdesk/data/holidays_*.json`

데스크는 15분 주기가 아니라 **이름 붙은 시장 슬롯**으로 돈다. 전략은 슬롯을 이름으로만 가리키고(`slots = {"screen", "fill_entry", "exits"}`), 시각·유예·시장은 이 모듈이 가진다.

## `SLOTS` (현지 시각 기준)
| 슬롯 | 시장 | 현지 시각 | KST 오늘(2026-10-29, EDT) | grace | LLM | finish_by | 하는 일 |
|---|---|---|---|---|---|---|---|
| `krx_open` | KRX | 09:05 | 09:05 | 25분 | 아니오 | — | 시초가 시세 → RISK → `fill_at=krx_open` PENDING 체결(시초가 +5bps) → 장부별 매도 → 잔고(INTRA) |
| `krx_cb` | KRX | 15:00 | 15:00 | 15분 | **예** | 15:20 | CB 종가배팅 스크린(실시간 랭킹) → jobs(거부권) → `finish`: 동시호가용 PENDING |
| `krx_close` | KRX | 15:40 | 15:40 | 60분 | 아니오 | — | 종가 시세 → RISK → 동시호가 주문 체결 → **EOD 잔고**(일손실 기준) |
| `krx_after` | KRX | 18:30 | 18:30 | 60분 | **예** | 19:30 | 장 마감 후 스크린(DART, 수급, 이벤트, 주간 모멘텀, 테마) → jobs → `finish`: 다음 시초가용 PENDING |
| `us_open` | US | 09:35 | 22:35 | 25분 | 아니오 | — | US 시초가 시세 → RISK → PENDING 체결 → 매도 |
| `us_close` | US | 16:10 | 05:10(+1일) | 60분 | 아니오 | — | US 종가 시세 → **EOD 잔고** → `fx_daily` 환율 |
| `us_er` | US | 17:00 | 06:00(+1일) | **예** | 60분 | 18:00 | 장 마감 후 실적 스크린(+ 주간 US 모멘텀) → jobs → `finish`: 다음 시초가용 PENDING |

장부 배정(어느 장부가 어디서 스크린·체결·매도하는지)은 `python3 schedule.py --assignments`로 뽑고 [`stockdesk/manual/ROUTINE.md`](../../../stockdesk/manual/ROUTINE.md)에 붙인다. `NEXT_FILL_SLOT = {KRX: krx_open, US: us_open}`(`OPEN_NEXT` 주문의 체결 슬롯), `EOD_SLOT = {KRX: krx_close, US: us_close}`.

## 거래일 판정
- `is_trading_day(market, day)` = 월~금이고 `data/holidays_<market>_<연도>.json`의 `dates`에 없음. 파일은 **수동**으로 관리한다(KRX 휴장일 안내, NYSE 캘린더 기준, TBC). 해당 연도 파일이 없으면 휴장일 없음으로 본다(주말만 쉼) — 연말에 다음 연도 파일을 미리 만든다.
- 날짜는 시장 현지 날짜다(`slot_date`): US 저녁 슬롯이 KST로는 다음 날 새벽이어도 그 US 거래일에 속한다.
- `trading_days_between`은 보유일(`positions.hold_days`)과 stale 일수 계산에, `next_trading_day`는 EV의 효력일 창에 쓴다.

## `due` 동작과 중복 방지
- 박스 cron: `*/5 * * * * cd /workspace/stockdesk && STOCKDESK_ROUTINE_VERSION=1 manual/variants.sh due --run`.
- `schedule.due(ts, already_run, llm=False)`: 오늘이 그 시장의 거래일이고, `start ≤ ts ≤ start + grace_min`이며, `already_run(slot, day)`가 거짓인 **코드 전용** 슬롯만 돌린다. LLM 슬롯은 `due`가 절대 돌리지 않는다(루틴이 `prepare`/`finish`).
- `already_run` = `market.db.slot_runs`에 (slot, day) 행이 있는지. `run_slot`이 끝나면 `mark_slot(slot, day, None, "slot")`, `prepare`는 `"prepare"`, `finish`는 `"finish"`로 같은 키에 덮어쓴다. 그래서 슬롯은 **하루 한 번**이고, 창을 놓치면(cron이 죽어 있다가 grace 뒤에 돌아오면) 그날은 건너뛴다.
- `due --run`은 슬롯마다 `state/cycle.lock`을 최대 60초 기다린다. 못 잡으면 종료 코드 3으로 그 5분은 건너뛰고 다음 5분에 다시 시도된다(창 안이면).
- 기록: `manual/variant_cycles/slots-YYYYMMDD.jsonl` 한 줄 = 한 슬롯(`{slot, day, kind, snapshot, books: {CODE: {risk, filled, exits, equity, equity_krw}}}`), 장부 DB `kv.slot_last:<slot>`, `logs/stockdesk.log`.

## 주문 수명 (`fill_at` / `expires_slot`)
| 주문 종류 | 만드는 곳 | `fill_at` = `expires_slot` | 체결 함수 |
|---|---|---|---|
| `OPEN_NEXT`(기본) | `krx_after`/`us_er`의 `prepare`(수치 장부) 또는 `finish`(LLM 장부) | `krx_open` / `us_open` | `fill_open` |
| `CLOSE_AUCTION`(CB) | `krx_cb`의 `finish` | `krx_close` | `fill_close_auction` |
| `LIMIT` | (쓰는 전략 없음) | 전략의 `fill_entry` | `fill_limit` |

- `_fill_pending`은 `status='PENDING' AND fill_at=<이 슬롯>`인 주문만 본다. 한 번 시도 뒤 FILLED/PARTIAL(포지션 생성) 또는 NO_PRICE/ZERO/EXPIRED(종료)이며 다음 슬롯으로 넘어가지 않는다. 장부가 `halted`면 `CANCELLED`.
- PENDING 매수 금액은 `encumbered`로 묶여 다음 주문의 여유 현금에서 빠진다.
- 체결 슬롯을 하루 건너뛰면(cron 누락) 그 주문은 다음 거래일 같은 슬롯에서 체결된다(`fill_at`에 날짜가 없다). 이는 신호보다 하루 늦은 체결이므로 ROUTINE의 "lastEOD" 점검으로 cron 누락을 잡는다.

## EOD 스냅샷 (`krx_close` / `us_close`)
- `equity_snapshot(kind="EOD")`: 그날의 EOD 행을 지우고 다시 쓴다(`cash, equity, realized, unrealized, deployed, fx_rate, fx_source, equity_krw`). 다른 슬롯은 `INTRA`.
- RISK의 일손실 한도(`daily_loss_blocked`)는 **오늘보다 앞선 마지막 EOD 행**을 기준으로 하고, 없으면 시작 잔고. `report --series`와 MDD는 EOD 행만 쓴다. EOD 슬롯이 빠지면 그날 수익률 열이 비고(직전 값 유지) 다음 날 일손실 기준이 하루 더 오래된 값이 된다.
- `us_close`에서 `fx_daily`를 기록한다(toss → erapi). KRX 슬롯도 Toss `fx`가 있으면 기록한다.

## 서머타임(DST) 영향
- KRX 슬롯의 KST는 고정이다. US 슬롯은 ET 기준이라 KST로는 **EDT 기간 22:35 / 05:10 / 06:00, EST 기간(2026-11-01 이후) 23:35 / 06:10 / 07:00**이다. 코드(`zoneinfo`)가 자동 처리하므로 cron 주기(`*/5`)와 ROUTINE의 "현지 시각" 표기만 지키면 된다.
- `kst_times(day)`는 특정 날짜의 KST를 돌려준다; `schedule.py`를 인자 없이 실행하면 오늘 기준 KST와 설명을 찍는다.
- 테스트: `manual/tests/test_schedule.py`(거래일, 휴장일, 창, DST 변환, `slot_date`).
