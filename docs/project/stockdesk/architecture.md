# 주식 데스크 아키텍처

[← 인덱스](../../../CLAUDE.md) · 코드: `stockdesk/run.py`(실행기), `schedule.py`(슬롯), `screen.py`(공유 fetch·Snapshot), `risk.py`, `strategies/`(장부 플러그인)

**모의 매매 전용.** 토스증권 Open API는 **시세 조회만** 쓰고 주문·계좌 코드는 없다(→ [toss-api-readonly.md](toss-api-readonly.md)). 8개 장부가 각각 **₩1,000,000**짜리 독립 모의 계좌로 KRX·US 시장을 본다(→ [books.md](books.md)).

## 전체 흐름
```
                 ┌───────────── 슬롯마다 1회 공유 fetch (screen.shared_snapshot) ─────────────┐
Toss Open API(시세만) ─┐                                                                      │
DART list.json ────────┼──► state/market.db (bars, snap, flow, disclosures, calendar, flags, fx) ──► Snapshot(읽기 전용, asof=슬롯 날짜)
Stooq / er-api / Finnhub┘                                                                      │
                                                                                               ▼
[박스] prepare <llm 슬롯> ──► 장부별 screen() ──► ban_set 재적용 ──► LLM 장부: jobs.jsonl ──► [Mac] Claude CLI 러너 ──► results.jsonl
                                              └──► 수치 장부: PENDING 주문(바로)                                           │
World Monitor Redis ──► regime_context(매크로 블록, 참고용) ──► 판단 프롬프트                                                 ▼
                                                                [박스] finish <runId> ──► buy_mode(claude/ev/veto) ──► PENDING 주문
                                                                                                                           │
[박스 cron */5] due --run ──► slot <체결 슬롯> ──► 시세 1회 ──► 공통 RISK ──► PENDING 체결(fill_at=이 슬롯) ──► 장부별 exits ──► equity(INTRA/EOD)
```
- 진입점: `stockdesk/manual/variants.sh` → `run.py` (`prepare` / `finish` / `slot` / `due`), 보고는 `report.py`.
- 데이터는 **슬롯 → `prepare`(후보·jobs) → Mac 판단 → `results.jsonl` → `finish`(PENDING 주문) → 다음 체결 슬롯의 `slot`(체결)** 순서로 흐른다. 주문은 만들어진 슬롯에서 체결되지 않고, `orders.fill_at`에 적힌 슬롯에서만 체결된다(→ [schedule.md](schedule.md)).

## 슬롯 기반 스케줄 (15분 주기가 아님)
코인 데스크의 15분 사이클과 달리 `schedule.SLOTS`에 이름 붙은 7개 슬롯(KRX 4, US 3)이 있고, 각 슬롯은 현지 시각과 유예(`grace_min`)를 가진다.
- **코드 전용 슬롯 4개**(`krx_open`, `krx_close`, `us_open`, `us_close`): 박스 cron이 5분마다 `due --run`으로 창이 열린 슬롯을 하루 한 번 돈다. LLM 없음.
- **LLM 슬롯 3개**(`krx_cb` 15:00, `krx_after` 18:30 KST, `us_er` 17:00 ET): `prepare` → Mac 판단 → `finish`를 루틴이 돈다. 각 슬롯에 `finish_by`(15:20 / 19:30 KST / 18:00 ET)가 있다. → [`stockdesk/manual/ROUTINE.md`](../../../stockdesk/manual/ROUTINE.md)
- 거래일 판정은 `data/holidays_<시장>_<연도>.json`(수동)으로 한다. US 슬롯의 KST는 서머타임에 따라 1시간 바뀐다.

## 박스와 Mac의 역할
| 위치 | 하는 일 | 경로 |
|---|---|---|
| 박스 (Linux, Grok Bot 작업 머신) | 데스크 실행(cron + 루틴), 장부 DB·market.db, 셀프호스팅 World Monitor | `/workspace/stockdesk`(가정), `/workspace/worldmonitor` |
| Mac (사용자 `minsu`) | Claude CLI(구독 로그인)로 판단 작업 실행, 이 git 저장소 | `/Users/minsu/workspace/Personal/worldmonitor-bot` |

- 판단 작업 파일은 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/jobs.jsonl`(`config.CLAUDE_CLI_STORE`, env `STOCKDESK_CLAUDE_CLI_STORE`)에 생기고, Mac `claude-cli-runs/<runId>/`로 복사돼 실행된 뒤 `results.jsonl`·`results.meta.json`이 박스로 돌아온다.
- Mac 러너는 **레거시 데스크의 `desk/manual/mac/claude_cli_runner.sh`를 그대로 재사용**한다(의도). 작업 줄은 같은 형식에 `pipeline: "stock"`, 결과 줄의 `claudeModel`/`requestedModel`/`requestedEffort`를 `finish`가 `vjudge.model`/`effort`에 기록한다. 깨진 결과 줄은 건너뛰고, 결과가 없는 후보는 `NO_JUDGE`로 SKIP(fail closed).
- `runId` 형식: `stock-<slot>-YYYYMMDD-HHMMSS`(KST).

## 저장소 분리: 장부 DB와 market.db
| 파일 | 내용 | 쓰는 쪽 |
|---|---|---|
| `state/books/<CODE>.db` (장부마다 1개) | `account`, `orders`, `fills`, `positions`, `equity`, `candidates`, `vcycles`, `vjudge`, `kv`(`halted`, `equity_peak`, `fx_start`, `slot_last:*`), `events` | `run.py`만 (장부별로 따로) |
| `state/market.db` (공유 1개) | `bars_daily`, `intraday_snap`, `flow_daily`, `disclosures`, `calendar`, `flags`, `fx_daily`, `universe`, `earnings`, `slot_runs` — 모든 행에 `source` | `screen.py`가 슬롯마다 1회 쓰고, 모든 장부·보고서가 읽는다 |

장부는 서로 독립이다. 같은 `Snapshot`을 읽지만 후보·판단·잔고·포지션은 장부마다 따로 있고, 한 장부의 중단(halt)은 다른 장부에 영향이 없다. → [data-sources.md](data-sources.md)

## RISK는 플러그인 밖에 있다
- `risk.py`는 모든 장부에 같은 규칙으로 **체결 슬롯마다 먼저** 돈다(`run_slot`: RISK → 체결 → 장부별 exits). 규칙 값은 `config.py`의 `risk.PROTECTED_KEYS`(`MAX_POSITION_PCT`, `DAILY_LOSS_LIMIT_PCT`, `MAX_DRAWDOWN_HALT_PCT`, `STALE_*`, `HALT_FLAGS`, `BAN_FLAGS`).
- 전략 플러그인은 `OVERRIDES`에 이 키를 넣을 수 없고 `risk`를 import할 수 없다. 둘 다 레지스트리(`strategies/__init__.py`)가 로드 시 `ValueError`로 거부해 `prepare`가 시작되지 않는다.
- `ban_set`(플래그·보호예수 해제 캘린더)은 `screen()` 결과에 `run.py`가 **다시** 적용한다. 전략이 금지 종목을 돌려줘도 후보가 되지 않는다.
- 진입 크기는 전략이 제안하고(`size()`), `risk.cap_entry_value`가 잔고의 20%와 묶이지 않은 현금으로 깎는다. `can_enter`(halt·일손실)가 거부하면 주문이 생기지 않는다.
- 장부별 매도(`Strategy.exits`)는 RISK가 방금 쓴 시세(`positions.last_price`)로만 판단한다. RISK 뒤에 추가만 한다.

## 코인 데스크에서 가져온 장점
| 장점 | 코인 데스크(`desk/`) | 주식 데스크(`stockdesk/`) |
|---|---|---|
| 독립 장부 | BASE·A~E 각 $1,000, 장부별 SQLite | 8개 장부 각 ₩1,000,000, `state/books/<CODE>.db`, 같은 스키마 형태(`common.BOOK_SCHEMA`) |
| RISK 우선·불가침 | `bots.risk_cycle`이 먼저, 장부별 매도는 뒤에 추가 | `risk.risk_pass`가 먼저; `PROTECTED_KEYS`와 레지스트리 검증으로 코드 수준에서 강제 |
| prepare/finish LLM 분리 | `run_variants.py prepare/finish`, Mac 러너 | `run.py prepare/finish`, 같은 러너·같은 작업/결과 형식, `--no-judge` |
| 모델·effort 기록 | `vjudge.model/effort`, `report` 분포 | 동일 (`vjudge.model/effort`, `report`의 `judge model/effort`) |
| 슬롯당 1회 공유 fetch + DB 캐시 | 사이클 안 메모이즈(스캔·보유자) | `screen.shared_snapshot` 1회 → `market.db`에 저장, `Snapshot`은 DB만 읽음(미래 데이터 누출 없음) |
| 생성 규칙 표 | `gen_rules_doc.py --write/--check` | 동일, `Strategy.describe()`가 `PARAMS`에서 문장을 만든다 |
| 고정 비율 크기 + RISK 상한 | C·D·E 고정 %, 유동성/50 상한 | `size_frac`(기본 `DEFAULT_SIZE_FRAC` 15%) + `MAX_POSITION_PCT` 20% + 유동성 상한(체결 모델) |
| 매크로 컨텍스트 | `desk/manual/regime_context.py` | `stockdesk/regime_context.py`(복사), 프롬프트 참고용만, 규칙 입력 아님 |
| Mac 러너 재사용 | `desk/manual/mac/claude_cli_runner.sh` | 같은 파일을 그대로 호출 |
| 잠금·루틴 버전·한국어 알림 | `state/variants.lock` 종료 코드 3, `DESK_ROUTINE_VERSION` | `state/cycle.lock` 종료 코드 3, `STOCKDESK_ROUTINE_VERSION` |

## 레거시 `desk/`와의 관계
- `desk/`(Solana 밈코인 모의 데스크)는 2026-10-29부터 **미가동·레거시**다. 수정하지 않는다.
- `stockdesk/`는 `desk/`에서 **코드를 복사**했고(`common.py`, `regime_context.py`, 잠금·prepare/finish·생성 표 패턴) **import하지 않는다.** 이유: `desk/common.py`가 `import config`를 그대로 하고 import 시점에 디렉터리를 만들어, 두 패키지에 `config.py`가 있으면 모호해진다(각 파일 머리의 `출처:` 주석).
- 유일한 공유 파일은 Mac 러너 `desk/manual/mac/claude_cli_runner.sh`다. 레거시 쪽이 지워지면 `stockdesk/` 아래로 옮겨야 한다.
- 파라미터 표기 규칙은 같다: 데스크 가정은 `ASSUMED`, 공식 출처 미확인은 `TBC`(코드 주석 그대로).
