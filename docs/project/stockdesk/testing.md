# 주식 데스크 테스트

[← 인덱스](../../../CLAUDE.md) · 위치: `stockdesk/manual/tests/` · 코인 데스크(레거시) 테스트는 [../testing.md](../testing.md)

모든 테스트는 `stockdesk/`에서 실행한다: `cd stockdesk && python3 manual/tests/<파일>.py`. 통과하면 마지막 줄에 **`ALL N CHECKS OK`**를 찍고, 실패하면 `FAIL <검사 이름>`으로 `AssertionError`가 난다. 통과 수는 이 출력에서 그대로 옮긴다.
`_harness.py`를 모든 테스트가 먼저 import한다: `stockdesk/`를 임시 폴더로 복사하고(`state/`, `logs/`, `variant_cycles/`, `.env`, `*.db` 제외), `STOCKDESK_FAKE_SNAPSHOT=1`, `STOCKDESK_CLAUDE_CLI_STORE=<임시>/claude-cli`, 모든 API 키 env를 비운다. **실제 `state/`와 네트워크를 건드리지 않는다.**

| 파일 | 무엇을 확인하려는가 | 비고 |
|---|---|---|
| `test_toss_readonly.py` | 토스 클라이언트가 **시세 조회만**인지: 클라이언트 표면(메서드·엔드포인트·경로)에 `FORBIDDEN_WORDS` 없음, `quotes.py` 소스에 주문·계좌 경로 문자열·계좌 헤더 없음, `_get`이 GET 아닌 메서드와 allowlist 밖 경로를 `assert`로 거부, 토큰 1회 발급·캐시·만료 여유(60초) 전 갱신·401 시 1회 재발급, `RateLimiter` 그룹별 간격, `TOSS_RPS`가 12/16/4, `http_json`이 `api.worldmonitor.app` 거부, 자격 증명 없으면 Toss 소스 `None`(대체 소스는 있음) | 가짜 HTTP, 네트워크 없음 |
| `test_fills_costs.py` | 체결·비용 모델: 동시호가 체결·상한·PARTIAL·`assumed` 경로, 1주 미달·최소 주문 미달 → ZERO, NO_PRICE, 시초가 ±5bps 슬립·상한, 지정가 접촉/미접촉, KRX 수수료·0.20% 거래세·ETF 면세, US 수수료·SEC·TAF, KRX 왕복 ≈0.23%, 정수주/소수주/소수주 끔, `fx_convert_once`와 `START_BALANCE_USD` 일치 | 순수 함수, 네트워크 없음 |
| `test_schedule.py` | 거래일·주말·휴장일(`data/holidays_*.json`), 다음/이전 거래일, 거래일 수 계산, KRX 슬롯 KST 고정, US 슬롯 KST의 DST 변동(22:35↔23:35, 05:10↔06:10), `due` 창(시작~grace)·`llm=False` 필터·이미 돈 슬롯 제외·주말 제외, `slot_date`가 ET 날짜, `finish_by`는 LLM 슬롯에만, `NEXT_FILL_SLOT`/`EOD_SLOT` 존재 | 네트워크 없음 |
| `test_strategy_contract.py` | 플러그인 계약: 8개 등록, `_template` 미등록, 파일명 정렬 순서, 레지스트리가 RISK 키 `OVERRIDES`·`import risk`·코드≠모듈명·비LLM 슬롯의 LLM 전략·시장/슬롯 불일치를 `ValueError`로 거부, 올바른 추가 플러그인은 등록됨, CB는 항상 다음 시초가 매도, 금지 종목은 후보·주문이 되지 않음, `halted`면 `can_enter` False·주문 없음 | 임시 플러그인 파일 생성, fake 시장 |
| `test_rules_docs.py` | 생성 규칙 표: 마커 사이 표가 코드와 다르면 `--check` 실패(diff), `--write`로 복원, `PARAMS` 바꾸면 검사 실패, 마커 없으면 `ValueError`, 범례(`legend`)에 모든 장부, **저장소의 `stockdesk/README.md`·`docs/project/stockdesk/books.md` 표가 코드와 같음**(어긋나면 `python3 gen_rules_doc.py --write`) | 임시 문서 + 실제 문서 검사, 파일 안 고침 |
| `test_report_series.py` | 수익률 궤적 보고: USD 장부가 `fx_convert_once`로 개설되고 `FX_FUND` 체결 행이 있음, 일간 시리즈가 모든 EOD 날짜를 덮고 INTRA 행은 무시, KRW 장부 수익률 = equity/1e6 − 1, USD 장부는 최신 `fx_daily`로 KRW 환산, EOD가 없는 날은 직전 값 유지, 주간 = ISO 주의 마지막 EOD, `--since`, EOD KRW 시리즈의 MDD·고점일, `report`에 ccy/KRW 수익률·수수료·세금·lastEOD·FX 효과 | 임시 장부 DB, 네트워크 없음 |
| `test_run_cycle.py` | 사이클 전 과정(fake 시장): `prepare <llm 슬롯>` → `jobs.jsonl` 형식(`pipeline: "stock"`, `MAX_JOBS` 라운드로빈·`OVER_JOB_CAP`) → 가짜 `results.jsonl`(정상·깨진 줄·누락) → `finish`가 `vjudge.model/effort`를 기록하고 `NO_JUDGE`/`JUDGE_UNPARSEABLE`/EV/거부권 규칙대로 PENDING 주문을 만듦 → `--no-judge`면 매수 없음 → `slot <체결 슬롯>`에서 RISK 먼저·`fill_at` 주문만 체결·장부별 매도·EOD 행, `slot_runs` 중복 방지, `already finished`/`unknown run`/잠금 종료 코드 3, `routine_version` 기록 | 임시 복사본, 네트워크·claude 없음 |

## 규칙
- `fills.py`, `risk.py`, `run.py`, `strategies/`, `schedule.py`, `quotes.py` 중 하나라도 바꾸면 **위 테스트를 전부** 돌리고 결과(각 `ALL N CHECKS OK`의 N)를 보고한다. 통과 수는 실행 출력에서 그대로 옮긴다.
- 전략 `PARAMS`를 바꾸면 `python3 gen_rules_doc.py --write` 뒤 `test_rules_docs.py`.
- 새 테스트는 `_harness.py`를 먼저 import하고, 실제 `state/`가 아니라 임시 복사본과 가짜 응답(네트워크 없음)을 쓴다.
- 단위 테스트는 실제 토스를 호출하지 않는다. 실호출 점검은 `python3 manual/toss_smoke.py [KRX코드] [US코드]`(읽기 전용, 허용 IP 필요, 공유 토큰 사용)로 사람이 한다. 같은 client_id로 박스 밖에서 돌리면 박스 토큰이 무효가 되니 주의. → [toss-api-readonly.md](toss-api-readonly.md)

## 오프라인 드라이런 (실제 DB 밖에서)
```bash
cd stockdesk
export STOCKDESK_FAKE_SNAPSHOT=1 STOCKDESK_CLAUDE_CLI_STORE=/tmp/stockdesk-dry/claude-cli
# 장부 DB·market.db는 state/에 생기므로, 실제 state/가 있는 머신에서는 stockdesk/를 임시 폴더로 복사한 뒤 그 안에서 돈다
manual/variants.sh prepare krx_after            # fake 시장 스크린, jobs.jsonl -> $STOCKDESK_CLAUDE_CLI_STORE/<runId>/
manual/variants.sh finish <runId> --no-judge    # 매수 없이 마감 (수치 장부 주문은 prepare에서 이미 생김)
manual/variants.sh slot krx_open                # 시초가 체결·RISK·매도·INTRA
manual/variants.sh slot krx_close               # EOD
manual/variants.sh report --series daily
```
- `STOCKDESK_BOOKS=CB` 같은 필터로 장부 하나만 돌릴 수 있다.
- fake 모드로 실제 `state/market.db`에 쓰면 `source="fake"` 행이 진짜 데이터와 섞인다. **실운영 폴더에서는 켜지 않는다.**
- Mac 판단 단계까지 포함한 드라이런은 `jobs.jsonl`을 Mac으로 옮겨 레거시 러너로 돌리고 `results.jsonl`을 `$STOCKDESK_CLAUDE_CLI_STORE/<runId>/`에 두면 된다(구독 사용량이 든다).
