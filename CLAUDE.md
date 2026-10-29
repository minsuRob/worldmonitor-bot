# worldmonitor-bot — 에이전트용 인덱스

> 이 파일은 루트에서 프롬프트를 시작할 때 가장 먼저 읽는 **목차**다. 자세한 내용은 아래 `docs/project/` 주제별 문서에 있다. `AGENTS.md`는 이 파일을 가리키는 심볼릭 링크다.

## 한 줄 요약
Solana 밈코인 **모의(페이퍼) 매매 데스크**(`desk/`)와 그 옆에서 매크로 데이터를 주는 **셀프호스팅 World Monitor**(`worldmonitor-selfhost/` 스크립트) 저장소다. 데스크는 박스(Linux)에서 15분마다 돌고, 후보 판단(Claude)은 사용자의 Mac에 있는 Claude CLI로 돌린다. 독립된 $1,000 모의 장부 5개(BASE·A·B·C·D)가 서로 다른 규칙으로 같은 시장을 본다.

## 절대 규칙
1. **모의 매매만.** 실제 주문, 지갑, 서명 키, 거래소 로그인, 결제 연결을 만들지 않는다.
2. **RISK의 결정을 뒤집지 않는다.** 공통 RISK 규칙을 느슨하게 하거나 건너뛰지 않는다. 장부별 매도는 RISK *뒤에* 추가만 한다.
3. **손익, 지연 시간, 커밋 해시를 지어내지 않는다.** 숫자는 장부 DB, 로그, `git` 출력에서만 가져온다.
4. **`api.worldmonitor.app`(호스팅 API)을 쓰지 않는다.** 체크를 통과시키려고도 쓰지 않는다. World Monitor는 셀프호스팅(`localhost`)만.
5. **커밋 금지:** `.env*`, API 키, `state/`(`*.db`), `logs/`, `manual/variant_cycles/`, `claude-cli-runs/`, `data/`.
6. 커밋 메시지는 **한글, 분류별**. 강제 푸시는 사용자 승인 없이 하지 않는다. → [conventions](docs/project/conventions.md)

> **15분 루틴을 돌리는 에이전트(Grok Bot 포함)는 [`desk/manual/ROUTINE.md`](desk/manual/ROUTINE.md)를 따른다.** 루틴을 바꾸려면 그 파일을 먼저 고치고 `routine-version`을 올린다.

## 디렉터리 지도
```
desk/                     데스크 코드 (Python 3, 표준 라이브러리만)
  config.py               모든 파라미터 (가이드 값 + 데스크 가정)
  common.py               SQLite 스키마·HTTP·수수료·AMM 체결 모델
  bots.py                 SCAN / VET / BOOK / SIZE / FILLS / RISK
  chief.py                감독 (상시 데스크용, 현재 미가동)
  report.py, check_alert.py   마감 보고 / 10% 변동 알림
  manual/                 15분 사이클용 5개 장부 실행기
    variants.sh           진입점: prepare | finish <runId> [--no-judge] | report
    run_variants.py       장부별 SCAN 필터·VET·판단 작업·SIZE·FILLS·RISK
    book_rules.py         장부별 규칙 (오버라이드, 사전 검사, 매수 규칙, 매도)
    gen_rules_doc.py      장부별 규칙 표를 코드에서 생성 (--write / --check)
    regime_context.py     판단 프롬프트에 넣는 매크로 블록 (WM Redis)
    ROUTINE.md            15분 루틴 기준 정의 (Grok Bot이 따름)
    mac/claude_cli_runner.sh   Mac 판단 러너 (구독 로그인만, 요청·실제 모델 기록)
    tests/                테스트·드라이런 스크립트
  analysis/               일회성 분석 자료 (예: d_cadence_0)
worldmonitor-selfhost/    World Monitor 셀프호스팅 스크립트 00~08 + setup.md
docs/                     리서치·가이드 요약·과거 상태 + project/(이 인덱스의 주제 문서)
tools/                    (git 제외) 예전 러너 사본. 루틴이 desk/manual/mac/ 경로로 바뀌면 지운다
claude-cli-runs/, data/   (git 제외) Mac에서 돈 Claude 판단 결과
```

## 주제별 문서
| 문서 | 이럴 때 읽는다 |
|---|---|
| [architecture.md](docs/project/architecture.md) | 전체 흐름, 박스와 Mac 역할, 데이터 출처를 알고 싶을 때 |
| [desk-bots.md](docs/project/desk-bots.md) | 6개 봇 파이프라인, VET 7개 검사, CHIEF 감독·중단 규칙을 볼 때 |
| [paper-books.md](docs/project/paper-books.md) | BASE·A·B·C·D 장부 규칙(VET, 크기, 매수, 매도)을 고치거나 설명할 때 |
| [ROUTINE.md](desk/manual/ROUTINE.md) | 15분 루틴의 기준 정의(단계, 복사, 실패 처리, 알림, Grok Bot 프롬프트)를 볼 때 |
| [runbook.md](docs/project/runbook.md) | 15분 사이클을 손으로 돌리거나, 잠금·Mac 연결 끊김·로그를 다룰 때 |
| [config-and-secrets.md](docs/project/config-and-secrets.md) | 환경 변수·키 이름, 비밀 저장 위치, git 제외 경로를 확인할 때 |
| [worldmonitor.md](docs/project/worldmonitor.md) | World Monitor 셀프호스팅·READY 체크·알려진 문제를 볼 때 |
| [testing.md](docs/project/testing.md) | 테스트를 돌리거나 새 테스트를 추가할 때 |
| [conventions.md](docs/project/conventions.md) | 커밋·푸시·보고 규칙과 금지 사항을 확인할 때 |
| [glossary.md](docs/project/glossary.md) | p_win, EV, Kelly 상한, VET 거절 코드 같은 용어를 찾을 때 |

기존 문서: [가이드 파라미터](docs/guide-params.md) · [리포스트 리서치](docs/research-reposts.md) · [2026-10-28 상태](docs/status.md)(과거 기록)

## 자주 쓰는 명령 (박스, `desk/`에서)
```bash
manual/variants.sh prepare                 # 공통 스캔 + 장부별 VET + jobs.jsonl 생성 (JSON 출력: runId, jobs)
manual/variants.sh finish <runId>          # Mac 결과 가져와 SIZE/FILLS/RISK
manual/variants.sh finish <runId> --no-judge   # Mac 불가 시: 매수 없음, RISK는 실행
manual/variants.sh report [--json]         # 5개 장부 비교 (장부 DB에서 읽음)
python3 manual/tests/test_books_v2.py      # 장부 규칙 테스트
python3 manual/tests/test_d_entry_filters.py
python3 manual/tests/test_rules_docs.py    # 규칙 표 = 코드 (어긋나면: python3 manual/gen_rules_doc.py --write)
python3 manual/tests/test_judge_record.py  # 판단 모델·effort 기록
```
Mac 판단 단계(저장소 루트): `CLAUDE_CLI_MODEL=fable CLAUDE_CLI_EFFORT=medium CLAUDE_CLI_MAX_JOBS=40 desk/manual/mac/claude_cli_runner.sh claude-cli-runs/<runId>/jobs.jsonl` → [ROUTINE](desk/manual/ROUTINE.md)
