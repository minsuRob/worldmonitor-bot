# World Monitor 셀프호스팅 (박스에서 실제로 쓴 절차)

upstream: https://github.com/koala73/worldmonitor (AGPL, 이 저장소에 포함하지 않음).
박스에서 검증한 버전: commit `828cd63b4b296a6583761ae128a97e701d929286`, v2.11.6.
**api.worldmonitor.app(호스팅 API)은 쓰지 않는다** — 데이터 엔드포인트가 API 키(Pro 플랜)를 요구함.

## 요구사항
- Node.js >= 20 (박스: v24.22.1), npm, git, curl, openssl
- Docker (Redis 컨테이너용). apt가 안 되면 정적 바이너리(03 스크립트)
- 포트: WM 3000(사용 중이면 다음 빈 포트를 `WM_PORT`로), Redis 127.0.0.1:6379, REST 어댑터 8079

## 순서
```bash
cd worldmonitor-selfhost
export WM_DIR=$HOME/worldmonitor TOOLS_DIR=$HOME/wm-tools WM_PORT=3000   # 00-env.sh 기본값 덮어쓰기
./01-clone-and-install.sh     # git clone --depth 1 + npm install (로컬 설치만, -g 없음)
./02-gen-secrets.sh           # .env / .env.local 생성(600 권한, 값 출력 안 함)
./03-docker-static.sh         # Docker가 이미 있으면 생략
./04-redis.sh                 # redis:7-alpine, --network host, 127.0.0.1 바인드, 비밀번호
./05-redis-rest-adapter.sh    # upstream docker/redis-rest-proxy.mjs + redis@4, :8079, Bearer=REDIS_TOKEN
./06-dev-server.sh            # npm run dev (vite), DEV_PORT=$WM_PORT
./07-seed.sh quick            # 키 없는 시더만: 3개 READY 체크 채우기
./08-checks.sh                # 3개 체크 + DexScreener + Kalshi + Polymarket (읽기 전용)
# 선택: ./07-seed.sh full     # upstream run-seeders.sh 전체(~228개, 수 시간, 키 없으면 다수 SKIP/FAIL)
```
중지: `./stop-all.sh` (Redis 데이터는 유지)

## READY 판정 기준 (3개 모두 실제 데이터일 때만)
| 체크 | 엔드포인트 | 실제 데이터 조건 |
|---|---|---|
| fear-greed | `/api/market/v1/get-fear-greed-index` | `unavailable`이 아니고 `compositeScore` 있음 |
| prediction | `/api/prediction/v1/list-prediction-markets?page_size=1` | `dataAvailable:true`, `markets` 비어있지 않음 |
| cross-source | `/api/intelligence/v1/list-cross-source-signals` | HTTP 200 + `signals` 비어있지 않음 |

시드 전 기본 상태: fear-greed `unavailable:true`, prediction `dataAvailable:false`, cross-source 503.

## 알려진 한계
- 박스 Docker는 iptables/bridge 없이 실행됨 → `--network host`만 가능. 그래서 docker-compose 전체 이미지가 아니라 **vite dev + Redis 컨테이너 + REST 어댑터** 조합으로 돌림.
- upstream REST 어댑터는 0.0.0.0에 바인드(옵션 없음). Bearer 토큰으로 보호되지만 포트를 외부에 열지 말 것.
- 시드 데이터는 TTL이 있어 만료됨. 주기 실행(cron 등)이 아직 없음 → 시간이 지나면 체크가 다시 비거나 503이 될 수 있음.
- cross-source 신호는 25개 소스 키 중 11개만 채워짐(키 없는 시더만 실행). 나머지는 API 키 필요(`docs/status.md` 참조).
- 예측(forecast) 엔드포인트는 LLM 키가 필요 → BOOK은 자체 확률이 없어 베팅하지 않음.
- Redis는 `EVAL`을 허용 목록 외로 거부함(로그에 `Command not allowed: EVAL`), 일부 기능 영향 가능.
- 전체 run-seeders.sh는 매우 느림(스크립트당 최대 240s 타임아웃).
