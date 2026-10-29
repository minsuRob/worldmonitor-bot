# 주식 데스크 슬롯 루틴 — 기준 정의

routine-version: **1** (2026-10-29) · 첫 판. 15분 주기가 아니라 **시장 슬롯**(`schedule.SLOTS`) 기준으로 돈다. 코인 데스크(`desk/manual/ROUTINE.md`, v2)는 2026-10-29부터 미가동이며 그 루틴은 돌리지 않는다.

> **루틴을 돌리는 에이전트(Grok Bot 등)는 이 파일을 따른다.** 루틴을 바꾸려면 이 파일을 먼저 고치고 `routine-version`을 올린 뒤 커밋한다. 슬롯·시각·장부 배정을 바꾸는 것은 코드(`schedule.py`, `strategies/`)이고, 바뀌면 아래 슬롯 표를 `python3 schedule.py --assignments` 출력으로 다시 붙인다. 루틴 쪽 설정에만 있는 동작은 이력이 남지 않으므로 두지 않는다.

## 절대 규칙 (요약)
모의 매매만 한다. 실제 주문·계좌·지갑·거래소 로그인·결제 연결을 만들지 않는다. **토스 Open API는 시세 조회만** 쓴다(주문·계좌 엔드포인트 코드 없음). RISK 결정을 뒤집지 않고, 포지션을 손으로 열거나 닫지 않는다. 손익·지연 시간·커밋 해시를 지어내지 않는다. `api.worldmonitor.app`을 쓰지 않는다. 전체는 저장소 루트 `CLAUDE.md`(=`AGENTS.md`).

## 어디서 무엇을
| 위치 | 경로 |
|---|---|
| 박스 (Linux) | 데스크 `/workspace/stockdesk`(가정; 저장소 `stockdesk/`와 같은 코드), 판단 작업 폴더 `/workspace/worldmonitor/data/claude-cli/<runId>/` (`config.CLAUDE_CLI_STORE`) |
| Mac (사용자 `minsu`) | 저장소 `/Users/minsu/workspace/Personal/worldmonitor-bot`, 판단 작업 폴더 `claude-cli-runs/<runId>/` (저장소 기준, git 제외) |

`runId`는 `stock-<slot>-YYYYMMDD-HHMMSS`(KST) 형식이다(`run.new_run_id`). 코인 데스크 runId와 접두어 `stock-`으로 구분된다.

## 스케줄
`python3 schedule.py --assignments` 출력(2026-10-29, 미국 서머타임 중). **US 슬롯의 KST는 서머타임에 따라 바뀐다**(2026-11-01 이후 +1시간: `us_open` 23:35, `us_close` 06:10, `us_er` 07:00 KST). 현지 시각이 기준이고 KST는 참고다.

| 슬롯 | 시장 | 현지 시각 | KST(오늘) | LLM | 스크린 | 진입 체결 | 매도 |
|---|---|---|---|---|---|---|---|
| `krx_open` | KRX | 09:05 | 09:05 | 아니오 | - | DT, EV, FL, MO, TH | CB, DT, EV, FL, MO, TH |
| `krx_cb` | KRX | 15:00 | 15:00 | 예 | CB | - | - |
| `krx_close` | KRX | 15:40 | 15:40 | 아니오 | - | CB | - |
| `krx_after` | KRX | 18:30 | 18:30 | 예 | DT, EV, FL, MO, TH | - | - |
| `us_open` | US | 09:35 | 22:35 | 아니오 | - | ER-US, MO-US | ER-US, MO-US |
| `us_close` | US | 16:10 | 05:10 | 아니오 | - | - | - |
| `us_er` | US | 17:00 | 06:00 | 예 | ER-US, MO-US | - | - |

- 거래일만 돈다(`data/holidays_<시장>_<연도>.json`, 수동 관리). 비거래일에는 `due`가 아무것도 돌리지 않고 LLM 슬롯도 건너뛴다.
- 슬롯마다 하루 한 번. `market.db`의 `slot_runs`(슬롯, 날짜)에 기록돼 두 번 돌지 않는다. 창(`time` ~ `time + grace_min`)을 놓치면 그날은 건너뛴다(`due`). → `docs/project/stockdesk/schedule.md`
- 이전 명령이 아직 돌고 있으면 새 명령을 시작하지 않는다(잠금 `state/cycle.lock`, 종료 코드 3).

## 박스 cron (코드 전용 슬롯, LLM 없음)
설치는 사용자가 박스에서 한 번 한다(`crontab -e`):
```
*/5 * * * * cd /workspace/stockdesk && STOCKDESK_ROUTINE_VERSION=1 manual/variants.sh due --run >> logs/due.log 2>&1
```
- 하는 일: 창이 열려 있고 아직 돌지 않은 **코드 전용 슬롯**(`krx_open`, `krx_close`, `us_open`, `us_close`)을 `slot <name>`으로 돈다. 각 슬롯: 시세 1회 fetch → 공통 RISK → PENDING 주문 체결(그 슬롯이 `fill_at`인 주문만) → 장부별 매도 → 잔고 스냅샷(`krx_close`/`us_close`는 EOD).
- LLM 슬롯 3개는 `due`가 돌리지 않는다(아래 단계 표, 루틴이 맡는다).
- 기록: `manual/variant_cycles/slots-YYYYMMDD.jsonl`(한 줄 = 한 슬롯), 장부 DB `kv.slot_last:<slot>`, `logs/stockdesk.log`.
- 잠금을 못 잡으면(종료 코드 3) 그 5분은 건너뛴다(정상, 알리지 않음). 다음 5분에 창이 아직 열려 있으면 다시 시도된다.

## LLM 슬롯 단계 (`krx_cb` · `krx_after` · `us_er`)
박스 명령은 모두 `/workspace/stockdesk`에서 실행하고, `prepare`와 `finish`에는 `STOCKDESK_ROUTINE_VERSION=1`을 붙인다. 이 값은 사이클 기록(`manual/variant_cycles/<runId>.json`, `.result.json`)에 `routine_version`으로 남는다. 각 슬롯의 현지 시각(`time`)에 1단계를 시작하고, **`finish`는 그 슬롯의 `finish_by` 전에 끝내야 한다**(`schedule.SLOTS`): `krx_cb` **15:20 KST**(동시호가 시작), `krx_after` **19:30 KST**, `us_er` **18:00 ET**. 늦으면 5단계를 `--no-judge`로 마친다.

| # | 어디서 | 명령 | 다음 |
|---|---|---|---|
| 1 | 박스 | `cd /workspace/stockdesk && STOCKDESK_ROUTINE_VERSION=1 manual/variants.sh prepare <slot>` | 출력 JSON 한 줄에서 `runId`, `jobs`를 읽는다 |
| 2 | 박스 | `jobs`가 0이면 3·4를 건너뛴다 | 5로 (`--no-judge`) |
| 3 | 박스 → Mac | 아래 "복사 절차" 3-1, 3-2 | 4로 |
| 4 | Mac | `cd /Users/minsu/workspace/Personal/worldmonitor-bot && CLAUDE_CLI_MODEL=fable CLAUDE_CLI_EFFORT=medium CLAUDE_CLI_MAX_JOBS=40 desk/manual/mac/claude_cli_runner.sh claude-cli-runs/<runId>/jobs.jsonl` | 아래 "복사 절차" 4-1 |
| 5 | 박스 | `cd /workspace/stockdesk && STOCKDESK_ROUTINE_VERSION=1 manual/variants.sh finish <runId>` (jobs = 0이거나 4단계를 못 했으면 끝에 `--no-judge`) | 판단 결과 → 장부별 매수 규칙(`buy_mode`) → PENDING 주문 생성(체결은 다음 체결 슬롯의 cron) |
| 6 | 박스 | `cd /workspace/stockdesk && manual/variants.sh report` | 8개 장부 비교표. 보고할 숫자는 이 출력과 장부 DB에서만 |

- `prepare`는 수치 장부(EV·FL·MO·MO-US)의 PENDING 주문도 같은 호출에서 만든다(LLM 없음). `jobs`는 LLM 장부(CB·DT·TH·ER-US) 후보 수다.
- `finish`는 주문만 만든다. 실제 체결은 `krx_cb`→`krx_close`(동시호가), `krx_after`→다음 `krx_open`, `us_er`→다음 `us_open`에서 cron이 한다.

### 복사 절차 (3·4단계)
코인 데스크와 같다. `runId` 접두어만 `stock-`이다.

| # | 도구 | 내용 |
|---|---|---|
| 3-1 | Mac Shell | `mkdir -p /Users/minsu/workspace/Personal/worldmonitor-bot/claude-cli-runs/<runId>` |
| 3-2 | CopyFromBox | 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/jobs.jsonl` → Mac `/Users/minsu/workspace/Personal/worldmonitor-bot/claude-cli-runs/<runId>/jobs.jsonl`. **도착 경로를 항상 전체 경로로 명시한다** |
| 4-1 | CopyToBox | Mac `claude-cli-runs/<runId>/results.jsonl`, `results.meta.json` → 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/` (두 파일 모두) |

- 상태 알림이 "Mac이 오프라인"이라고 해도 그대로 믿지 않는다. **항상 실제 Shell 명령을 한 번 시도하고, 실패하면 약 20초 뒤 한 번 더 시도한다.** 두 번 다 실패해야 "Mac 불가"로 본다.

### 4단계 세부
- 러너는 **레거시 데스크의 `desk/manual/mac/claude_cli_runner.sh`를 그대로 쓴다**(의도된 재사용; 작업 줄 형식 `pipeline: "stock"`만 다르다). `stockdesk/`에는 러너가 없다.
- 판단 모델·노력 수준은 **`CLAUDE_CLI_MODEL=fable`, `CLAUDE_CLI_EFFORT=medium`으로 고정**한다. 요청값은 `requestedModel`/`requestedEffort`, 실제 모델은 `claudeModel`로 기록되고, `finish`가 장부 DB `vjudge.model`/`effort`에 넣고 `report`가 장부별 분포를 보여 준다.
- `CLAUDE_CLI_MAX_JOBS`는 박스 `config.MAX_JOBS`(기본 40, env `CLAUDE_CLI_MAX_JOBS`)와 **같아야** 한다. 상한을 넘은 후보는 `OVER_JOB_CAP`으로 SKIP된다.
- 러너는 API 키를 지우고 구독 로그인만 쓴다. 확인: `results.meta.json`의 `anthropicApiKeyUnset: true`.

## 실패 처리
| 상황 | 할 일 |
|---|---|
| Mac이 잠들었거나 연결이 끊김, 러너 실패 (실제 명령 2회 실패) | `finish <runId> --no-judge`로 마친다. LLM 장부는 아무것도 사지 않는다(`NO_JUDGE`). RISK·매도는 cron 슬롯에서 그대로 돈다. 알림은 아래 "Mac/Claude 불가" 규칙대로 |
| `prepare`/`finish`/`slot`이 종료 코드 3 (잠금) | 같은 슬롯에서 바로 다시 시도하지 않는다. 잠금 파일 `state/cycle.lock`에 잡은 쪽(`pid=... <what> since ...`)이 적혀 있다. `finish`는 최대 120초, cron `due`는 60초 기다린 뒤 포기한다 |
| `finish`가 "results.jsonl missing" | 3·4단계 복사를 확인한다. 다시 가져올 수 없으면 `--no-judge` |
| `finish`가 "already finished" | 이미 반영된 사이클이다. 다시 적용하지 않는다 |
| `finish`가 "unknown run" | `runId` 오타 또는 박스 `manual/variant_cycles/<runId>.json`이 없다. `prepare` 출력의 `runId`를 다시 확인 |
| `prepare`가 "already exists" | 같은 초에 10번 넘게 돈 것(같은 초의 두 번째 실행은 `runId` 끝에 `-2`, `-3`…이 붙어 정상 진행된다). 이번 슬롯을 건너뛰고 `slot_runs`·`vcycles`에서 어느 `runId`가 살았는지 확인 |
| `prepare`가 "unknown slot" | 슬롯 이름은 위 표의 7개만 |
| `finish_by`를 넘김 | `--no-judge`로 마친다. 늦은 판단으로 주문을 만들지 않는다 |
| `report`의 `lastEOD`가 어제(직전 거래일)보다 오래됨 | EOD 슬롯(`krx_close`/`us_close`) cron이 안 돈 것. `logs/due.log` 마지막 줄을 그대로 알림. 포지션을 손으로 고치지 않는다 |
| 그 밖의 0이 아닌 종료 코드 | 마지막 출력 줄을 그대로 알림. 포지션을 손으로 고치지 않는다 |

`prepare`가 끝났는데 `finish`를 못 한 `runId`는 장부 DB `vcycles`에서 `ts_finish`가 비어 있다. 다음 체결 슬롯 전에 그 `runId`를 `--no-judge`로 마칠지는 사용자에게 묻는다.

## 알림
사용자에게는 **한국어로, 아래 경우에만** 보낸다. 그 밖에는 아무것도 보내지 않는다(정상 슬롯, jobs = 0, 주문 없는 슬롯 포함). 숫자는 `finish`/`slot`/`report` 출력과 장부 DB에서만 옮긴다.

| 경우 | 담을 내용 |
|---|---|
| 모의 매수 체결 (`slot` 출력의 `filled` > 0, `slots-YYYYMMDD.jsonl`) | 장부, 종목(시장·코드·이름), 금액, 체결가, 부분 체결 여부(`partial`), 유동성 기준(`liquidity_ref`) |
| 매도: RISK 청산(`UNMEASURABLE_CLOSE`, `FLAG_…`) 또는 장부별 매도(`exits` > 0, 규칙 이름 `CB_SELL_NEXT_OPEN`, `DT_STOP_-7%`, `MO_REBALANCE_OUT` 등) | 장부, 종목, 규칙, 실현 손익(장부 통화) |
| 장부 중단(HALT: 고점 대비 −15%, `report`에 `HALTED`) 또는 포지션 HALTED(거래정지) | 장부, 사유(출력 그대로). 해제는 사용자가 한다 |
| Mac/Claude 불가가 **LLM 슬롯 2회 연속** (슬롯마다 실제 명령 2회 실패) | 한 번의 장애에 한 번만 보낸다. 보낸 뒤 `manual/variant_cycles/MAC_UNAVAILABLE_NOTIFIED.txt`를 만들고, 이 파일이 있으면 다시 보내지 않는다. 판단이 정상으로 끝난 `finish`가 나오면 이 파일을 지운다 |
| 8개 장부 비교 | 하루 1회, 한국 시간 **09:00 이후 첫 실행**에서 `manual/variants.sh report --series daily`(KRW 기준 수익률 열·MDD) 요약 + `report` 표의 장부별 잔고·수익률·보유 |
| 실패 처리 표에서 "알림"이라고 한 경우 | 출력 그대로 |

- cron 슬롯에서 일어난 체결·매도는 루틴이 다음 실행에서 `manual/variant_cycles/slots-YYYYMMDD.jsonl`의 새 줄(직전 실행 이후)을 읽어 위 규칙대로 알린다.

## Grok Bot 루틴에 넣을 프롬프트
```
worldmonitor-bot 주식 데스크(stockdesk) 슬롯 루틴을 돈다.
먼저 /workspace/stockdesk/manual/ROUTINE.md(Mac에서는 저장소의 stockdesk/manual/ROUTINE.md)를 읽고 그 슬롯 표, 단계, 복사 절차, 실패 처리, 알림 규칙을 그대로 따른다.
LLM 슬롯(krx_cb 15:00, krx_after 18:30 KST, us_er 17:00 ET)에만 prepare → Mac 판단 → finish를 하고, 각 슬롯의 finish_by 전에 finish를 끝낸다. 코드 전용 슬롯은 박스 cron이 돌리므로 직접 돌리지 않고 report의 lastEOD로 살아 있는지만 확인한다.
박스 prepare/finish 명령에는 STOCKDESK_ROUTINE_VERSION=<ROUTINE.md의 routine-version>을 붙인다.
코인 데스크(/workspace/desk) 루틴은 돌리지 않는다.
ROUTINE.md에 없는 동작은 하지 않고, 바꿔야 하면 사용자에게 알린다.
```

## 박스와 저장소 동기화
박스 `/workspace/stockdesk`는 이 저장소 `stockdesk/`와 같은 코드지만 git 이력이 따로다. 이 파일, 전략, 스케줄을 바꾸면 박스 쪽에도 반영해야 루틴과 cron이 새 정의를 읽는다.
- 슬롯이 돌지 않는 틈(`pgrep -af "run.py"`가 비어 있고 `state/cycle.lock`이 비어 있을 때, 슬롯 창 밖)에 한다.
- 먼저 `state/books/*.db`, `state/market.db`를 `sqlite3 .backup`으로 `state/backup-<시각>/`에 백업한다.
- Mac에서 `git archive HEAD stockdesk/`로 추적 파일만 묶어 박스에 풀고(`__pycache__`, `._*` 제외; `state/`, `logs/`, `.env`, `manual/variant_cycles/`는 git 제외라 덮어쓰지 않는다), 박스 git에 "동기화: ... (Mac main <hash>)"로 커밋한다.
- 박스 `.env`(`TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`, `DART_API_KEY`, `FINNHUB_API_KEY`)는 저장소에 없다. 값은 적지 않고 이름만 문서화한다. → `docs/project/stockdesk/toss-api-readonly.md`
