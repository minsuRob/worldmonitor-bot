# 설정과 비밀

[← 인덱스](../../CLAUDE.md) · 코드: `desk/config.py`, `desk/manual/regime_context.py`, `worldmonitor-selfhost/02-gen-secrets.sh`

> **값은 절대 문서·커밋·로그에 쓰지 않는다.** 이 문서에는 이름만 적는다.

## 비밀 저장 위치
| 위치 | 내용 |
|---|---|
| GCP Secret Manager, 프로젝트 `worldmonitor-bot` | 원본 저장소. Mac의 `gcloud`로 접근 |
| 박스 `/workspace/worldmonitor/.env.local` | World Monitor가 읽는 키 + 로컬 Redis REST 접속 정보 (600 권한) |
| 박스 `/workspace/desk/.env` | 데스크용 `HELIUS_API_KEY` (git 제외) |
| 박스 `/workspace/secrets/helius_api_key.txt` | `config.py`가 env에 키가 없을 때 읽는 대체 파일 |

## 데스크가 읽는 환경 변수
| 이름 | 용도 | 없으면 |
|---|---|---|
| `HELIUS_API_KEY` | Helius RPC·DAS (읽기 전용) | 공용 Solana RPC → RugCheck로 대체, 보유자 수는 알 수 없음 |
| `SOLANA_RPC_URL` | 선택. 가장 먼저 시도할 RPC | 무시 |
| `WM_PORT` | 셀프호스팅 World Monitor 포트 (기본 3000) | 3000 |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | 매크로 블록용 WM Redis (없으면 `.env.local`에서 읽음) | 매크로 블록이 `unavailable` |
| `CLAUDE_CLI_MAX_JOBS` | 사이클당 판단 작업 상한 (기본 40) | 40 |
| Mac 러너: `CLAUDE_CLI_MODEL`, `CLAUDE_CLI_EFFORT`, `CLAUDE_CLI_TIMEOUT` | 모델·노력 수준·작업당 시간 제한 (모델·노력 수준은 요청값으로 기록됨) | CLI 기본값(기록은 `null`) / 300초 |
| `DESK_ROUTINE_VERSION` | 루틴이 따른 `ROUTINE.md` 버전. 사이클 기록에 `routine_version`으로 남음 | `null` |

## Secret Manager에 있는 이름 (2026-10-29 `gcloud secrets list`)
`ACLED_EMAIL`, `ACLED_PASSWORD`, `AISSTREAM_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `COMTRADE_API_KEYS`, `EIA_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`, `GIE_API_KEY`, `HELIUS_API_KEY`, `IMF_API_KEY`, `NASA_FIRMS_API_KEY`, `OPENAQ_API_KEY`, `OPENROUTER_API_KEY`, `OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`, `OTX_API_KEY`, `SAM_GOV_API_KEY`, `SIGNUP_PASSWORD`, `USDA_FAS_API_KEY`, `USDA_FAS_PSD_API_KEY`, `WAQI_API_KEY`, `WTO_API_KEY`

`.env.local`에는 위 대부분과 함께 `UPSTASH_REDIS_REST_URL`/`TOKEN`, `API_BASE_URL`, `FORECAST_LLM_*_PROVIDER_ORDER`, `OPENROUTER_FREE_DISABLED` 같은 설정이 있다. World Monitor 쪽 키 용도는 [worldmonitor.md](worldmonitor.md)를 본다.

## Claude CLI 비용 안전
러너는 `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock/Vertex/Foundry 스위치를 지우고 구독 로그인만 쓴다. 이 동작을 바꾸지 않는다. → [architecture.md](architecture.md#claude-cli-러너-mac)

## git 제외 경로
루트 `.gitignore`: `state/`, `logs/`, `__pycache__/`, `*.db`, `*.db-*`, `.env*`, `worldmonitor/`, `tools/`, `.claude-cli-runs/`, `claude-cli-runs/`, `data/`
`desk/.gitignore`: `state/`, `logs/`, `__pycache__/`, `manual/variant_cycles/`, `.env`, `*.key`

- `tools/`가 제외돼 있어서 예전 러너 사본 `tools/claude_cli_runner.sh`는 추적되지 않는다. 정본은 추적되는 `desk/manual/mac/claude_cli_runner.sh`다.
- 커밋 전에 스테이징된 diff에서 키처럼 보이는 문자열을 검사한다. → [conventions.md](conventions.md)
