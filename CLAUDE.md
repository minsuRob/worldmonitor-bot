# worldmonitor-bot — 에이전트용 인덱스

> 이 파일은 루트에서 프롬프트를 시작할 때 가장 먼저 읽는 **목차**다. 자세한 내용은 아래 `docs/project/` 주제별 문서에 있다. `AGENTS.md`는 이 파일을 가리키는 심볼릭 링크다.

## 한 줄 요약
**주식(KRX·US) 모의(페이퍼) 매매 데스크**(`stockdesk/`, **현재 주력**)와 매크로 데이터를 주는 **셀프호스팅 World Monitor**(`worldmonitor-selfhost/` 스크립트) 저장소다. 주식 데스크는 박스(Linux)에서 시장 **슬롯**(15분 주기 아님)마다 돌고, 후보 판단(Claude)은 사용자의 Mac에 있는 Claude CLI로 돌린다. 독립된 ₩1,000,000 모의 장부 8개(CB·DT·EV·FL·MO·TH·ER-US·MO-US)가 서로 다른 규칙으로 같은 시장을 본다. 토스 Open API는 시세 조회만 쓴다. 예전 Solana 밈코인 데스크(`desk/`, $1,000 모의 장부)는 **2026-10-29부터 레거시·미가동**이며 수정하지 않는다.

## 절대 규칙
1. **모의 매매만.** 실제 주문, 지갑, 서명 키, 거래소 로그인, 결제 연결을 만들지 않는다.
2. **RISK의 결정을 뒤집지 않는다.** 공통 RISK 규칙을 느슨하게 하거나 건너뛰지 않는다. 장부별 매도는 RISK *뒤에* 추가만 한다.
3. **손익, 지연 시간, 커밋 해시를 지어내지 않는다.** 숫자는 장부 DB, 로그, `git` 출력에서만 가져온다.
4. **`api.worldmonitor.app`(호스팅 API)을 쓰지 않는다.** 체크를 통과시키려고도 쓰지 않는다. World Monitor는 셀프호스팅(`localhost`)만.
5. **토스 Open API는 시세 조회만.** 주문·계좌 엔드포인트 코드를 만들지 않는다(`stockdesk/quotes.py` allowlist, `test_toss_readonly.py`). → [toss-api-readonly](docs/project/stockdesk/toss-api-readonly.md)
6. **커밋 금지:** `.env*`(`.env.example` 제외), API 키, `state/`(`*.db`), `logs/`, `manual/variant_cycles/`, `claude-cli-runs/`, `data/`(루트), `stockdesk/state/`, `stockdesk/logs/`, `stockdesk/manual/variant_cycles/`, `stockdesk/.env`.
7. 커밋 메시지는 **한글, 분류별**. 강제 푸시는 사용자 승인 없이 하지 않는다. → [conventions](docs/project/conventions.md)

> **슬롯 루틴을 돌리는 에이전트(Grok Bot 포함)는 [`stockdesk/manual/ROUTINE.md`](stockdesk/manual/ROUTINE.md)를 따른다.** 루틴을 바꾸려면 그 파일을 먼저 고치고 `routine-version`을 올린다. 레거시 15분 루틴(`desk/manual/ROUTINE.md`)은 돌리지 않는다.

## 디렉터리 지도
```
stockdesk/                주식 데스크 (현재 주력; Python 3, 표준 라이브러리만; desk/에서 코드 복사, import 안 함)
  config.py               공통 숫자만: 경로, 잔고·FX, 비용, 체결 상한, 유니버스, RISK, 토스 한도 (ASSUMED/TBC 표시)
  common.py               시간·로거·http_json(api.worldmonitor.app 거부)·장부 SQLite 스키마·kv/event
  marketdb.py             공유 시장 캐시 state/market.db (봉·스냅·수급·공시·캘린더·플래그·환율·유니버스·실적·slot_runs)
  quotes.py               읽기 전용 어댑터: TossQuotes(시세만, ALLOWED_PATHS·FORBIDDEN_WORDS·RateLimiter), DART, Stooq, er-api, Finnhub
  screen.py               슬롯당 1회 공유 fetch → market.db, Snapshot, 유니버스, ban_set, FAKE_SNAPSHOT 합성 시장
  fills.py                모의 체결·비용 모델 (동시호가·시초가 슬립·지정가·호가단위·소수주·1회 환전)
  risk.py                 공통 RISK (먼저 실행, PROTECTED_KEYS, 중단 플래그, stale, 일손실, 낙폭 중단)
  judge.py                jobs.jsonl/results.jsonl 형식(pipeline "stock"), EV·buy_mode 결정
  schedule.py             SLOTS 7개(KRX 4·US 3), 휴장일, 거래일 수, due(), --assignments 슬롯 표
  run.py                  prepare <slot> | finish <runId> [--no-judge] | slot <name> | due [--run]
  report.py               장부별 보고(ccy/KRW 수익률, FX 효과, MDD, 수수료, 판단 모델) + --series daily|weekly
  gen_rules_doc.py        장부별 규칙 표 생성 (--write / --check) → README.md, docs/project/stockdesk/books.md
  regime_context.py       판단 프롬프트 매크로 블록 (WM Redis; desk/에서 복사)
  strategies/             장부 플러그인 (파일명 = 소문자 코드): __init__(레지스트리 검증), base, _template, cb dt ev fl mo mo_us th er_us
  manual/variants.sh      진입점: prepare | finish | slot | due | report
  manual/ROUTINE.md       슬롯 루틴 기준 정의 (Grok Bot이 따름)
  manual/tests/           _harness.py(임시 복사본·fake 시장) + test_*.py
  data/                   휴장일(수동), US 유니버스 시드, DART corp_code (git 추적)
  state/ logs/ .env       (git 제외) 장부 DB·market.db·잠금, 로그, 비밀 (.env.example만 추적)
desk/                     (레거시: 코인, 2026-10-29부터 미가동, 수정하지 않음) Solana 밈코인 데스크
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
| **주식 데스크 (현재)** | |
| [stockdesk/architecture.md](docs/project/stockdesk/architecture.md) | 슬롯 기반 전체 흐름, 박스/Mac 역할, 장부 DB와 market.db 분리, RISK 위치, 코인 데스크에서 가져온 것 |
| [stockdesk/books.md](docs/project/stockdesk/books.md) | 8개 장부 규칙(생성 표), 공통 규칙·RISK 값, 장부별 스크린·프롬프트 요지, **새 전략 추가 절차** |
| [stockdesk/data-sources.md](docs/project/stockdesk/data-sources.md) | 토스 엔드포인트(공식 스펙, 2026-10-29 실호출 확인)·플래그 매핑·토스에 없는 것, 보조 어댑터, market.db 테이블, data/ 파일, FAKE_SNAPSHOT |
| [stockdesk/fill-and-cost-model.md](docs/project/stockdesk/fill-and-cost-model.md) | 체결 함수·비용·호가단위·정수주·1회 환전·가정값 |
| [stockdesk/schedule.md](docs/project/stockdesk/schedule.md) | SLOTS 표, 거래일 판정, due와 slot_runs, 주문 수명, EOD, DST |
| [stockdesk/testing.md](docs/project/stockdesk/testing.md) | stockdesk 테스트 목록·실행법·오프라인 드라이런 |
| [stockdesk/toss-api-readonly.md](docs/project/stockdesk/toss-api-readonly.md) | 시세 조회 전용 선언과 강제 방법, 키 발급·허용 IP, 비밀 이름, 레이트리미터 |
| [stockdesk/manual/ROUTINE.md](stockdesk/manual/ROUTINE.md) | 슬롯 루틴 기준 정의(슬롯 표, cron, LLM 슬롯 단계, 복사, 실패 처리, 알림, Grok Bot 프롬프트) |
| **코인 데스크 (레거시, 미가동)** | |
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

## 자주 쓰는 명령 — 주식 데스크 (박스, `stockdesk/`에서)
```bash
manual/variants.sh prepare <slot>          # krx_cb | krx_after | us_er: 스크린 → jobs.jsonl(LLM 장부) + PENDING 주문(수치 장부). JSON 출력: runId, jobs
manual/variants.sh finish <runId>          # Mac 결과 → buy_mode → PENDING 주문 (체결은 다음 체결 슬롯)
manual/variants.sh finish <runId> --no-judge   # Mac 불가 시: LLM 장부 매수 없음
manual/variants.sh slot <name>             # 체결 슬롯 직접 실행: 시세 → RISK → 체결 → 매도 → 잔고
manual/variants.sh due [--run]             # 박스 cron */5: 창이 열린 코드 전용 슬롯
manual/variants.sh report [--json]         # 8개 장부 비교 (장부 DB에서 읽음)
manual/variants.sh report --series daily|weekly [--since YYYY-MM-DD] [--csv path]
python3 schedule.py --assignments          # ROUTINE.md 슬롯 표
python3 gen_rules_doc.py --write|--check   # 규칙 표 (README.md, docs/project/stockdesk/books.md)
python3 manual/tests/test_toss_readonly.py # 시세 조회 전용 강제
python3 manual/tests/test_fills_costs.py; python3 manual/tests/test_schedule.py
python3 manual/tests/test_strategy_contract.py; python3 manual/tests/test_rules_docs.py
python3 manual/tests/test_report_series.py; python3 manual/tests/test_run_cycle.py
```
Mac 판단 단계(저장소 루트, 레거시 러너를 그대로 재사용): `CLAUDE_CLI_MODEL=fable CLAUDE_CLI_EFFORT=medium CLAUDE_CLI_MAX_JOBS=40 desk/manual/mac/claude_cli_runner.sh claude-cli-runs/<runId>/jobs.jsonl` → [ROUTINE](stockdesk/manual/ROUTINE.md)
오프라인 드라이런: `STOCKDESK_FAKE_SNAPSHOT=1 STOCKDESK_CLAUDE_CLI_STORE=/tmp/stockdesk-cli manual/variants.sh prepare krx_after` → [testing](docs/project/stockdesk/testing.md)

## 자주 쓰는 명령 — 코인 데스크 (레거시, 미가동; 박스, `desk/`에서)
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
