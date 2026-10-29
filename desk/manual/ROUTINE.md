# 15분 장부 루틴 — 기준 정의

routine-version: **1** (2026-10-29)

> **15분 루틴을 돌리는 에이전트(Grok Bot 등)는 이 파일을 따른다.** 루틴을 바꾸려면 이 파일을 먼저 고치고 `routine-version`을 올린 뒤 커밋한다. 루틴 쪽 설정에만 있는 동작은 이력이 남지 않으므로 두지 않는다.
>
> 이 파일은 2026-10-29에 저장소 문서(`docs/project/runbook.md`, `architecture.md`)와 그때 돌던 Grok Bot 루틴(실행 명령, 복사 절차, 알림 규칙)을 대조해 맞춘 기준이다.

## 절대 규칙 (요약)
모의 매매만 한다. 실제 주문·지갑·서명 키·거래소 로그인·결제 연결을 만들지 않는다. RISK 결정을 뒤집지 않고, 포지션을 손으로 열거나 닫지 않는다. 손익·지연 시간·커밋 해시를 지어내지 않는다. `api.worldmonitor.app`을 쓰지 않는다. 전체는 저장소 루트 `CLAUDE.md`(=`AGENTS.md`).

## 어디서 무엇을
| 위치 | 경로 |
|---|---|
| 박스 (Linux) | 데스크 `/workspace/desk`, 판단 작업 폴더 `/workspace/worldmonitor/data/claude-cli/<runId>/` |
| Mac (사용자 `minsu`) | 저장소 `/Users/minsu/workspace/Personal/worldmonitor-bot`, 판단 작업 폴더 `claude-cli-runs/<runId>/` (저장소 기준, git 제외) |

## 스케줄
- 15분마다 한 번, 아래 1~6단계를 순서대로 한 번 돈다.
- 이전 사이클이 아직 돌고 있으면 새 사이클을 시작하지 않는다(잠금이 종료 코드 3으로 거부한다).

## 단계
박스 명령은 모두 `/workspace/desk`에서 실행하고, `prepare`와 `finish`에는 환경 변수 `DESK_ROUTINE_VERSION=1`을 붙인다. 이 값은 사이클 기록(`manual/variant_cycles/<runId>.json`, `.result.json`)에 `routine_version`으로 남는다.

| # | 어디서 | 명령 | 다음 |
|---|---|---|---|
| 1 | 박스 | `cd /workspace/desk && DESK_ROUTINE_VERSION=1 manual/variants.sh prepare` | 출력 JSON 한 줄에서 `runId`, `jobs`를 읽는다 |
| 2 | 박스 | `jobs`가 0이면 3·4를 건너뛴다 | 5로 (`--no-judge`) |
| 3 | 박스 → Mac | 아래 "복사 절차" 3-1, 3-2 | 4로 |
| 4 | Mac | `cd /Users/minsu/workspace/Personal/worldmonitor-bot && CLAUDE_CLI_MODEL=fable CLAUDE_CLI_EFFORT=medium CLAUDE_CLI_MAX_JOBS=40 desk/manual/mac/claude_cli_runner.sh claude-cli-runs/<runId>/jobs.jsonl` | 아래 "복사 절차" 4-1 |
| 5 | 박스 | `cd /workspace/desk && DESK_ROUTINE_VERSION=1 manual/variants.sh finish <runId>` (jobs = 0이거나 4단계를 못 했으면 끝에 `--no-judge`) | 매수 규칙 → SIZE → FILLS → RISK → 장부별 매도 |
| 6 | 박스 | `cd /workspace/desk && manual/variants.sh report` | 5개 장부 비교표. 보고할 숫자는 이 출력과 장부 DB에서만 |

### 복사 절차 (3·4단계)
| # | 도구 | 내용 |
|---|---|---|
| 3-1 | Mac Shell | `mkdir -p /Users/minsu/workspace/Personal/worldmonitor-bot/claude-cli-runs/<runId>` |
| 3-2 | CopyFromBox | 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/jobs.jsonl` → Mac `/Users/minsu/workspace/Personal/worldmonitor-bot/claude-cli-runs/<runId>/jobs.jsonl`. **도착 경로를 항상 전체 경로로 명시한다** (기본 위치에 두지 않는다) |
| 4-1 | CopyToBox | Mac `claude-cli-runs/<runId>/results.jsonl`, `results.meta.json` → 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/` (두 파일 모두) |

- 상태 알림이 "Mac이 오프라인"이라고 해도 그대로 믿지 않는다. **항상 실제 Shell 명령을 한 번 시도하고, 실패하면 약 20초 뒤 한 번 더 시도한다.** 두 번 다 실패해야 "Mac 불가"로 본다.

### 4단계 세부
- 러너는 저장소에서 추적되는 `desk/manual/mac/claude_cli_runner.sh`를 쓴다. 예전 `tools/claude_cli_runner.sh`(git 제외)는 루틴이 새 경로로 바뀐 것을 확인한 뒤에만 지운다.
- 판단 모델·노력 수준은 **`CLAUDE_CLI_MODEL=fable`, `CLAUDE_CLI_EFFORT=medium`으로 고정**한다. 빼면 CLI 기본값으로 바뀌므로 빼지 않는다. 요청값은 결과에 `requestedModel`/`requestedEffort`로, CLI가 실제로 쓴 모델은 `claudeModel`로 기록되고, `finish`가 이를 장부 DB `vjudge.model`/`effort`에 넣고 `report`가 장부별 분포를 보여 준다.
- `CLAUDE_CLI_MAX_JOBS`는 박스 `run_variants.py`(기본 40)와 **같아야** 한다.
- 러너는 API 키를 지우고 구독 로그인만 쓴다. 이 동작을 끄지 않는다. 확인: `results.meta.json`의 `anthropicApiKeyUnset: true`, `jobsOnSubscription`.

## 실패 처리
| 상황 | 할 일 |
|---|---|
| Mac이 잠들었거나 연결이 끊김, 러너 실패 (실제 명령 2회 실패) | `finish <runId> --no-judge`로 마친다. 아무것도 사지 않고 RISK·장부별 매도는 돈다. 알림은 아래 "Mac/Claude 불가" 규칙대로 |
| `prepare`/`finish`가 종료 코드 3 (잠금) | 같은 사이클에서 다시 시도하지 않는다. 잠금 파일 `state/variants.lock`에 잡은 쪽(`pid=... since ...`)이 적혀 있다 |
| `finish`가 "results.jsonl missing" | 3·4단계 복사를 확인한다. 다시 가져올 수 없으면 `--no-judge` |
| `finish`가 "import failed" | 출력 그대로 알림. 같은 `runId`를 `--no-judge`로 마칠지는 사용자 판단 |
| `finish`가 "already finished" | 이미 반영된 사이클이다. 다시 적용하지 않는다 |
| `prepare`가 "already exists" | 같은 초에 두 번 돈 것. 이번 사이클을 건너뛴다 |
| 그 밖의 0이 아닌 종료 코드 | 마지막 출력 줄을 그대로 알림. 포지션을 손으로 고치지 않는다 |

`prepare`가 끝났는데 `finish`를 못 한 `runId`는 장부 DB `vcycles`에서 `ts_finish`가 비어 있다. 다음 사이클 전에 그 `runId`를 `--no-judge`로 마칠지는 사용자에게 묻는다.

## 알림
사용자에게는 **한국어로, 아래 경우에만** 보낸다. 그 밖에는 아무것도 보내지 않는다(정상 사이클, jobs = 0, 매수 없는 사이클 포함). 숫자는 `finish`/`report` 출력과 장부 DB에서만 옮긴다.

| 경우 | 담을 내용 |
|---|---|
| 모의 매수 체결 (BUY fill) | 장부, 토큰, 금액, 체결가, 슬리피지 |
| 보유 포지션이 직전 사이클 대비 10% 넘게 변동 | 장부, 토큰, 직전 → 현재 가격, 변동률, 미실현 손익 |
| RISK 청산 또는 C/D 장부별 매도 | 장부, 규칙, 실현 손익($) |
| 데스크 중단(halt) | 중단 사유(출력 그대로) |
| Mac/Claude 불가가 **2사이클 연속** (사이클마다 실제 명령 2회 실패) | 한 번의 장애에 한 번만 보낸다. 보낸 뒤 `manual/variant_cycles/MAC_UNAVAILABLE_NOTIFIED.txt`를 만들고, 이 파일이 있으면 다시 보내지 않는다. 판단이 정상으로 끝난 사이클(Claude 결과를 가져온 `finish`)이 나오면 이 파일을 지운다 |
| 5개 장부 비교 | 한국 시간 09:00, 21:00 **이후 첫 사이클**에서 하루 두 번, `report` 기준 장부별 잔고·수익률·보유 |
| 실패 처리 표에서 "알림"이라고 한 경우 | 출력 그대로 |

- `desk/check_alert.py`(10% 변동 알림)는 상시 데스크의 `state/summary.json`을 읽는다. 15분 장부 루틴과는 연결돼 있지 않다. 위 10% 규칙은 루틴이 장부 DB 가격으로 판단한다.

## Grok Bot 루틴에 넣을 프롬프트
```
15분마다 worldmonitor-bot 장부 루틴을 돈다.
먼저 /workspace/desk/manual/ROUTINE.md(Mac에서는 저장소의 desk/manual/ROUTINE.md)를 읽고 그 단계, 복사 절차, 실패 처리, 알림 규칙을 그대로 따른다.
박스 prepare/finish 명령에는 DESK_ROUTINE_VERSION=<ROUTINE.md의 routine-version>을 붙인다.
ROUTINE.md에 없는 동작은 하지 않고, 바꿔야 하면 사용자에게 알린다.
```

## 박스와 저장소 동기화
박스 `/workspace/desk`는 이 저장소 `desk/`와 같은 코드지만 git 이력이 따로다. 이 파일이나 러너를 바꾸면 박스 쪽에도 반영해야 루틴이 새 정의를 읽는다.
- 사이클이 돌지 않는 틈(사이클 직후, `pgrep -af run_variants`가 비어 있고 `logs/variants.log` 마지막 사이클이 끝난 때)에 한다.
- 먼저 `state/desk.db`, `state/variants/*.db`를 `sqlite3 .backup`으로 `state/backup-<시각>/`에 백업한다.
- Mac에서 `git archive HEAD desk/`로 추적 파일만 묶어 박스에 풀고(`__pycache__`, `._*` 제외), 박스 git에 "동기화: ... (Mac main <hash>)"로 커밋한다.
