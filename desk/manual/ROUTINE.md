# 15분 장부 루틴 — 기준 정의

routine-version: **1** (2026-10-29)

> **15분 루틴을 돌리는 에이전트(Grok Bot 등)는 이 파일을 따른다.** 루틴을 바꾸려면 이 파일을 먼저 고치고 `routine-version`을 올린 뒤 커밋한다. 루틴 쪽 설정에만 있는 동작은 이력이 남지 않으므로 두지 않는다.
>
> 이 파일은 2026-10-29에 저장소 문서(`docs/project/runbook.md`, `architecture.md`)를 바탕으로 **새로 쓴 기준**이다. 그 전까지 Grok Bot 루틴에만 있던 정의는 저장소에서 볼 수 없었다. 아래에서 "기존 루틴 확인 필요"로 표시한 곳은 루틴 원문과 대조해 채운다.

## 절대 규칙 (요약)
모의 매매만 한다. 실제 주문·지갑·서명 키·거래소 로그인·결제 연결을 만들지 않는다. RISK 결정을 뒤집지 않고, 포지션을 손으로 열거나 닫지 않는다. 손익·지연 시간·커밋 해시를 지어내지 않는다. `api.worldmonitor.app`을 쓰지 않는다. 전체는 저장소 루트 `CLAUDE.md`(=`AGENTS.md`).

## 어디서 무엇을
| 위치 | 경로 |
|---|---|
| 박스 (Linux) | 데스크 `/workspace/desk`, 판단 작업 폴더 `/workspace/worldmonitor/data/claude-cli/<runId>/` |
| Mac (사용자 `minsu`) | 저장소 `~/workspace/Personal/worldmonitor-bot`, 판단 작업 폴더 `claude-cli-runs/<runId>/` |

## 스케줄
- 15분마다 한 번, 아래 1~6단계를 순서대로 한 번 돈다.
- 이전 사이클이 아직 돌고 있으면 새 사이클을 시작하지 않는다(잠금이 종료 코드 3으로 거부한다).

## 단계
박스 명령은 모두 `/workspace/desk`에서, 환경 변수 `DESK_ROUTINE_VERSION=1`을 붙여 실행한다. 이 값은 사이클 기록(`manual/variant_cycles/<runId>.json`, `.result.json`)에 `routine_version`으로 남는다.

| # | 어디서 | 명령 | 다음 |
|---|---|---|---|
| 1 | 박스 | `DESK_ROUTINE_VERSION=1 manual/variants.sh prepare` | 출력 JSON 한 줄에서 `runId`, `jobs`를 읽는다 |
| 2 | 박스 | `jobs`가 0이면 3·4를 건너뛴다 | 5로 |
| 3 | 박스 → Mac | `/workspace/worldmonitor/data/claude-cli/<runId>/jobs.jsonl`을 Mac `claude-cli-runs/<runId>/jobs.jsonl`로 복사 | 복사 방법은 기존 루틴 확인 필요 |
| 4 | Mac 저장소 루트 | `CLAUDE_CLI_MAX_JOBS=40 desk/manual/mac/claude_cli_runner.sh claude-cli-runs/<runId>/jobs.jsonl` | 같은 폴더의 `results.jsonl`, `results.meta.json`을 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/`로 복사 |
| 5 | 박스 | `DESK_ROUTINE_VERSION=1 manual/variants.sh finish <runId>` (jobs = 0이거나 4단계를 못 했으면 끝에 `--no-judge`) | 매수 규칙 → SIZE → FILLS → RISK → 장부별 매도 |
| 6 | 박스 | `manual/variants.sh report` | 5개 장부 비교표. 보고할 숫자는 이 출력과 장부 DB에서만 |

### 4단계 세부
- 러너는 저장소에서 추적되는 `desk/manual/mac/claude_cli_runner.sh`를 쓴다. 예전 `tools/claude_cli_runner.sh`(git 제외)는 루틴이 새 경로로 바뀐 뒤 지운다.
- `CLAUDE_CLI_MAX_JOBS`는 박스 `run_variants.py`(기본 40)와 **같아야** 한다.
- 모델·노력 수준은 고정하지 않는다. `CLAUDE_CLI_MODEL`, `CLAUDE_CLI_EFFORT`를 쓰면 그 값이, 안 쓰면 `null`이 결과에 `requestedModel`/`requestedEffort`로 기록되고, CLI가 실제로 쓴 모델은 `claudeModel`로 기록된다. `finish`가 이를 장부 DB `vjudge.model`/`effort`에 넣고 `report`가 장부별 분포를 보여 준다.
- 러너는 API 키를 지우고 구독 로그인만 쓴다. 이 동작을 끄지 않는다. 확인: `results.meta.json`의 `anthropicApiKeyUnset: true`, `jobsOnSubscription`.

## 실패 처리
| 상황 | 할 일 |
|---|---|
| Mac이 잠들었거나 연결이 끊김, 러너 실패 | `finish <runId> --no-judge`로 마친다. 아무것도 사지 않고 RISK·장부별 매도는 돈다. 알림 대상 |
| `prepare`/`finish`가 종료 코드 3 (잠금) | 같은 사이클에서 다시 시도하지 않는다. 잠금 파일 `state/variants.lock`에 잡은 쪽(`pid=... since ...`)이 적혀 있다 |
| `finish`가 "results.jsonl missing" | 3·4단계 복사를 확인한다. 다시 가져올 수 없으면 `--no-judge` |
| `finish`가 "import failed" | 출력 그대로 알림. 같은 `runId`를 `--no-judge`로 마칠지는 사용자 판단 |
| `finish`가 "already finished" | 이미 반영된 사이클이다. 다시 적용하지 않는다 |
| `prepare`가 "already exists" | 같은 초에 두 번 돈 것. 이번 사이클을 건너뛴다 |
| 그 밖의 0이 아닌 종료 코드 | 마지막 출력 줄을 그대로 알림. 포지션을 손으로 고치지 않는다 |

`prepare`가 끝났는데 `finish`를 못 한 `runId`는 장부 DB `vcycles`에서 `ts_finish`가 비어 있다. 다음 사이클 전에 그 `runId`를 `--no-judge`로 마칠지는 사용자에게 묻는다.

## 알림
- 보낼 때: 위 실패 처리 표에서 "알림"이라고 한 경우, 그리고 5단계를 `--no-judge`로 마친 경우.
- 보내지 않을 때: 정상 사이클(jobs = 0 포함).
- 알림 채널·문구·재시도 간격은 **기존 루틴 확인 필요**. 정해지면 이 절에 적고 버전을 올린다.
- `desk/check_alert.py`(10% 변동 알림)는 상시 데스크의 `state/summary.json`을 읽는다. 15분 장부 루틴과는 연결돼 있지 않다.

## Grok Bot 루틴에 넣을 프롬프트
```
15분마다 worldmonitor-bot 장부 루틴을 돈다.
먼저 /workspace/desk/manual/ROUTINE.md(Mac에서는 저장소의 desk/manual/ROUTINE.md)를 읽고 그 단계와 실패 처리를 그대로 따른다.
박스 명령에는 DESK_ROUTINE_VERSION=<ROUTINE.md의 routine-version>을 붙인다.
ROUTINE.md에 없는 동작은 하지 않고, 바꿔야 하면 사용자에게 알린다.
```

## 박스와 저장소 동기화
박스 `/workspace/desk`는 이 저장소 `desk/`와 같은 코드지만 git 이력이 따로다. 이 파일이나 러너를 바꾸면 박스 쪽에도 반영해야 루틴이 새 정의를 읽는다(동기화 방법은 기존 루틴 확인 필요).
