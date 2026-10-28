# worldmonitor-bot — 모의(페이퍼) 트레이딩 데스크

**모의 매매 전용.** 실제 주문, 지갑, 거래소 로그인, API 키, 결제 연결이 없다. 공개 읽기 전용 시장 데이터만 쓴다.
(DexScreener, 공용 Solana RPC, Kalshi·Polymarket 공개 API, 자체 호스팅 World Monitor)

## 구성
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

## 실행
1. World Monitor 셀프호스팅: [`worldmonitor-selfhost/setup.md`](worldmonitor-selfhost/setup.md)
2. 체크 확인: `worldmonitor-selfhost/08-checks.sh`
3. 데스크 시작: `cd desk && WM_PORT=3000 ./start.sh` / 중지: `./stop.sh`
4. 상태: `desk/state/summary.json`(1분마다), 로그 `desk/logs/supervisor.log`
5. 보고: `python3 desk/report.py [YYYY-MM-DD]`, 알림: `python3 desk/check_alert.py` (cron 등으로 주기 실행)

> 현재 데스크는 **시작하지 않은 상태**다. [`docs/status.md`](docs/status.md) 참고.

## 문서
- [리포스트 리서치](docs/research-reposts.md)
- [가이드 파라미터 요약](docs/guide-params.md)
- [현재 상태·체크 결과·필요한 키 목록](docs/status.md)

## 라이선스 메모
World Monitor(koala73/worldmonitor)는 AGPL 제3자 코드라 이 저장소에 포함하지 않는다. `05-redis-rest-adapter.sh`는 클론한 upstream 파일을 복사해서 실행한다.
