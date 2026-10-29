# World Monitor (셀프호스팅)

[← 인덱스](../../CLAUDE.md) · 설치 절차 전체: [`worldmonitor-selfhost/setup.md`](../../worldmonitor-selfhost/setup.md) (이 문서는 요약과 데스크 연결점만)

## 무엇인가
- upstream `koala73/worldmonitor` (AGPL). **이 저장소에 포함하지 않는다**(`.gitignore`의 `worldmonitor/`). 검증 버전: commit `828cd63`, v2.11.6.
- 박스에서는 `/workspace/worldmonitor`에 설치돼 있다. 구성: vite dev 서버(`localhost:3000`) + Redis 7 컨테이너(`127.0.0.1:6379`) + Upstash 호환 REST 어댑터(`:8079`).
- **`api.worldmonitor.app`은 쓰지 않는다.** 체크가 비어도 호스팅 API로 넘어가지 않는다.

## 스크립트 (`worldmonitor-selfhost/`)
| 스크립트 | 하는 일 |
|---|---|
| `00-env.sh` | 공통 경로·포트 (`WM_DIR`, `TOOLS_DIR`, `WM_PORT`) |
| `01-clone-and-install.sh` | clone + 로컬 `npm install` |
| `02-gen-secrets.sh` | `.env`/`.env.local` 생성 (600 권한, 값 출력 안 함) |
| `03-docker-static.sh` | apt가 안 될 때 Docker 정적 바이너리 (iptables 없이 → `--network host`) |
| `04-redis.sh` | Redis 7, 127.0.0.1, 비밀번호 |
| `05-redis-rest-adapter.sh` | upstream `redis-rest-proxy.mjs`, Bearer 토큰 |
| `06-dev-server.sh` | `npm run dev` |
| `07-seed.sh quick\|full` | quick: 키 없는 시더로 READY 체크 3개 채우기 / full: upstream 전체(~228개, 수 시간) |
| `08-checks.sh` | READY 체크 3개 + DexScreener + Kalshi + Polymarket (읽기 전용) |
| `stop-all.sh` | 중지 (Redis 데이터 유지) |

## 데스크와 연결되는 곳
| 용도 | 코드 | 실패하면 |
|---|---|---|
| READY 체크 3개 (fear-greed, prediction, cross-source) | `config.WM_CHECKS`, `chief.run_checks` | `degraded`, READY 아님. BOOK 쉼, 밈코인은 계속 |
| BOOK 예측시장 목록 | `bots.book_tick` | BOOK 베팅 없음 |
| 15분 사이클 매크로 블록 (BTC, VIX, 분위기, WTI, 헤드라인) | `manual/regime_context.py` (Redis REST로 직접 읽음, 600자 이하) | 블록에 `unavailable`. 매매 규칙에는 영향 없음 |

READY 판정 조건 표는 `setup.md`의 "READY 판정 기준"을 본다.

## 알려진 한계 (`setup.md`, `docs/status.md` 기준)
- 시드 데이터에 TTL이 있고 주기 실행(cron)이 없다 → 시간이 지나면 체크가 다시 비거나 503이 될 수 있다.
- cross-source는 25개 소스 키 중 11개만 채워진다(키 없는 시더만 실행 시).
- forecast는 LLM 키가 필요하다 → BOOK은 자체 확률이 없어 베팅하지 않는다.
- Redis가 `EVAL`을 거부한다(`Command not allowed: EVAL`).
- REST 어댑터는 0.0.0.0에 바인드된다. 포트를 외부에 열지 않는다.
- 이 밖에 개별 시더 문제(예: WAQI 파서, COMTRADE, 오래된 인사이트)가 보고된 적이 있으나 **저장소 문서로 확인되지 않았다**. 고치기 전에 박스 로그로 재현한다.

## 키
World Monitor 시더가 쓰는 키 이름은 [config-and-secrets.md](config-and-secrets.md). 값은 GCP Secret Manager(`worldmonitor-bot`) → 박스 `.env.local`.
