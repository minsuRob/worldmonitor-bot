# 운영 런북: 15분 사이클

[← 인덱스](../../CLAUDE.md) · 코드: `desk/manual/variants.sh`, `desk/manual/run_variants.py`, Mac `desk/manual/mac/claude_cli_runner.sh`

15분마다 Grok Bot 루틴이 아래 순서를 한 번 돈다. **루틴의 기준 정의(복사, 실패 처리, 알림, Grok Bot 프롬프트)는 [`desk/manual/ROUTINE.md`](../../desk/manual/ROUTINE.md)다.** 이 문서는 손으로 돌릴 때의 요약이다.

## 단계
| # | 어디서 | 명령 | 결과 |
|---|---|---|---|
| 1 | 박스 `/workspace/desk` | `manual/variants.sh prepare` | JSON 한 줄: `runId`, `jobs`, `jobsFile`, 장부별 후보·통과 수. 사이클 기록 `manual/variant_cycles/<runId>.json` |
| 2 | (jobs = 0이면 3·4 건너뛰고 5로) | | |
| 3 | 박스 → Mac | `jobs.jsonl`을 Mac `claude-cli-runs/<runId>/jobs.jsonl`로 복사 | 박스 원본: `/workspace/worldmonitor/data/claude-cli/<runId>/jobs.jsonl` |
| 4 | Mac 저장소 루트 | `CLAUDE_CLI_MAX_JOBS=40 desk/manual/mac/claude_cli_runner.sh claude-cli-runs/<runId>/jobs.jsonl` (모델·노력 수준은 고정하지 않음. `CLAUDE_CLI_MODEL`/`CLAUDE_CLI_EFFORT` 요청값과 CLI가 보고한 실제 모델이 작업마다 기록되고, `finish`가 장부 DB `vjudge.model`/`effort`에 넣는다) | 같은 폴더에 `results.jsonl`, `results.meta.json`. 박스 run 폴더로 다시 복사 |
| 5 | 박스 | `manual/variants.sh finish <runId>` (jobs = 0이거나 Mac 불가면 `--no-judge`) | 결과 가져오기 → 장부별 매수 규칙 → SIZE → FILLS → RISK → 장부별 매도. 기록 `manual/variant_cycles/<runId>.result.json` |
| 6 | 박스 | `manual/variants.sh report` | 5개 장부 비교표 (모든 숫자는 장부 DB에서) |

- `runId` 형식: `meme-var-YYYYMMDD-HHMMSS` (KST, 초 단위라 같은 분에 두 번 돌아도 겹치지 않음).
- `CLAUDE_CLI_MAX_JOBS`는 박스(`run_variants.py`, 기본 40)와 Mac 러너가 **같아야** 한다. 넘친 후보는 장부별 `OVER_JOB_CAP`.
- `finish`는 같은 `runId`를 두 번 적용하지 않는다. `prepare`는 이미 쓰인 `runId`를 거부한다.

## 잠금
- `prepare`/`finish`는 `desk/state/variants.lock`에 `flock`을 잡는다. 이미 잡혀 있으면 **종료 코드 3**으로 거부하고, 잠금 파일에 잡은 쪽(`pid=... since ...`)이 적혀 있다.
- 프로세스가 죽으면 잠금은 자동으로 풀린다. 수동 실행은 루틴과 겹치지 않을 때만 한다.

## Mac을 쓸 수 없을 때
- Mac이 잠들었거나 연결이 끊겨 러너를 못 돌리면 `finish <runId> --no-judge`로 마친다. **아무것도 사지 않고**, RISK와 장부별 매도는 정상으로 돈다(`NO_JUDGE`).
- 알림을 보내는 조건은 [`ROUTINE.md`](../../desk/manual/ROUTINE.md#알림)에 있다. 알림 채널·문구는 아직 기존 루틴과 대조하지 않았다.
- 사용자 쪽 조치: Mac을 깨우고 Grok Bot 데스크톱 앱을 연다.
- 러너 결과 확인: `results.meta.json`의 `ok`/`failed`, `anthropicApiKeyUnset`, `authStatus`(구독 로그인인지).

## 로그와 기록 (모두 git 제외)
| 무엇 | 위치 (박스 `desk/` 기준) |
|---|---|
| 사이클 로그 | `logs/variants.log` |
| 사이클 입력·결과 | `manual/variant_cycles/<runId>.json`, `<runId>.result.json` |
| 장부 | `state/desk.db`(BASE), `state/variants/{A,B,C,D}.db` |
| 보유자 스냅샷 | `state/holder_snapshots.db` |
| Claude 작업·결과 (박스) | `/workspace/worldmonitor/data/claude-cli/<runId>/` (`jobs.jsonl`, `results.jsonl`, `stored.jsonl`) |
| Claude 작업·결과 (Mac) | `claude-cli-runs/<runId>/` |

## 보고할 때
- 사용자가 상태를 물으면 최근 후보의 VET 통과·거절 이유와 Claude 판단(p_win, EV)을 같이 보여 준다.
- 숫자는 `report` 출력, `*.result.json`, 장부 DB에서만 가져온다. 시간은 KST로 쓴다.
