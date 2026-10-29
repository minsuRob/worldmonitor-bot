# worldmonitor-bot — 모의(페이퍼) 트레이딩 데스크

**모의 매매 전용.** 실제 주문, 계좌, 지갑, 거래소 로그인, 결제 연결이 없다. 읽기 전용 시장 데이터만 쓴다.

## 소개 — 주식 데스크 `stockdesk/` (현재)
KRX·US 주식 모의 데스크. 독립된 **₩1,000,000** 모의 장부 8개(CB 종가배팅, DT 공시 추종, EV 이벤트 캘린더, FL 수급 추종, MO 모멘텀, TH 테마, ER-US 실적 후 추세, MO-US 모멘텀)가 시장 **슬롯**(KRX 09:05/15:00/15:40/18:30, US 09:35/16:10/17:00 현지)마다 같은 데이터를 보고 서로 다른 규칙으로 판단한다.
- 데이터: **토스증권 Open API는 시세 조회만**(주문·계좌 코드 없음, allowlist로 강제), DART 공시, Stooq·er-api·Finnhub 대체, 셀프호스팅 World Monitor 매크로 블록.
- 코드 전용 슬롯은 박스 cron(`due --run`), LLM 슬롯 3개는 `prepare`(박스) → Claude CLI(Mac, 구독 로그인) → `finish`(박스). 공통 RISK가 모든 체결 슬롯에서 먼저 돌고 장부 플러그인은 이를 바꿀 수 없다.
- 시작점: [`stockdesk/README.md`](stockdesk/README.md), 루틴 [`stockdesk/manual/ROUTINE.md`](stockdesk/manual/ROUTINE.md), 문서 [`docs/project/stockdesk/`](docs/project/stockdesk/).

```
stockdesk/               주식 데스크 (Python 3, 표준 라이브러리만)
  config.py              공통 숫자 (ASSUMED/TBC 표시)      run.py       prepare | finish | slot | due
  quotes.py              읽기 전용 어댑터 (토스 시세만)    report.py    장부 비교·수익률 시리즈
  screen.py marketdb.py  슬롯당 1회 fetch → state/market.db  risk.py    공통 RISK
  fills.py               모의 체결·비용 모델               schedule.py  슬롯·거래일
  strategies/            장부 플러그인 8개 + _template.py   manual/      variants.sh, ROUTINE.md, tests/
```

## 레거시 — 코인 데스크 `desk/` (2026-10-29부터 미가동, 수정하지 않음)
Solana 밈코인 모의 데스크. 공개 읽기 전용 데이터(DexScreener, 공용 Solana RPC, Kalshi·Polymarket 공개 API, 자체 호스팅 World Monitor). 아래는 당시 구성 기록이다.

### 구성
- 6개 봇: **SCAN → VET → BOOK → SIZE → FILLS → RISK**, 그리고 감독 프로세스 **CHIEF**.
- CHIEF 규칙
  - 포지션을 열거나·크기를 정하거나·닫지 않는다. RISK의 결정을 뒤집지 않는다.
  - VET를 통과하지 않은 것은 SIZE로 가지 않는다. RISK는 자체 타이머로 돈다.
  - 봇이 응답을 2번 놓치면 1번 재시작·기록. 같은 봇이 1시간에 2번 죽으면 데스크 중단(아무것도 닫지 않음, RISK 유지).
  - World Monitor가 비었거나 오류면 degraded, BOOK 휴식. 밈코인 데스크는 DexScreener로 계속.
  - READY는 3개 World Monitor 체크가 모두 실제 데이터를 줄 때만. api.worldmonitor.app 사용 금지.
  - 커밋 해시·지연 시간·손익을 지어내지 않는다.

```
desk/                    데스크 코드 (Python 3.9+, 표준 라이브러리만)
  config.py              파라미터 (가이드 값)
  common.py              SQLite(WAL)·HTTP·수수료·체결 모델
  bots.py                scan / vet / book / size / fills / risk
  chief.py               감독: 하트비트, 재시작/중단, 체크, summary.json, 23:00 마감 보고
  report.py              한국어 마감 보고 (실제 상태만)
  check_alert.py         10% 넘게 움직였을 때만 짧은 한국어 알림
  start.sh / stop.sh     백그라운드 시작 / 중지 (stop은 포지션을 닫지 않음)
worldmonitor-selfhost/   World Monitor 셀프호스팅 스크립트 + setup.md (upstream 소스는 미포함)
docs/                    리서치·가이드 요약·현재 상태
```

### 실행 (레거시)
1. World Monitor 셀프호스팅: [`worldmonitor-selfhost/setup.md`](worldmonitor-selfhost/setup.md)
2. 체크 확인: `worldmonitor-selfhost/08-checks.sh`
3. 데스크 시작: `cd desk && WM_PORT=3000 ./start.sh` / 중지: `./stop.sh`
4. 상태: `desk/state/summary.json`(1분마다), 로그 `desk/logs/supervisor.log`
5. 보고: `python3 desk/report.py [YYYY-MM-DD]`, 알림: `python3 desk/check_alert.py` (cron 등으로 주기 실행)

> 현재 데스크는 **시작하지 않은 상태**다. [`docs/status.md`](docs/status.md) 참고.

## 문서
- **에이전트·작업자 시작점: [`CLAUDE.md`](CLAUDE.md)** (`AGENTS.md`는 같은 파일) → 주제별 구조 문서 [`docs/project/`](docs/project/)
- [리포스트 리서치](docs/research-reposts.md)
- [가이드 파라미터 요약](docs/guide-params.md)
- [현재 상태·체크 결과·필요한 키 목록](docs/status.md)

## 라이선스 메모
World Monitor(koala73/worldmonitor)는 AGPL 제3자 코드라 이 저장소에 포함하지 않는다. `05-redis-rest-adapter.sh`는 클론한 upstream 파일을 복사해서 실행한다.
