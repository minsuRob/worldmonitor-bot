# 아키텍처

[← 인덱스](../../CLAUDE.md)

## 전체 흐름 (15분 사이클)
```
DexScreener ──► SCAN(공통 1회) ──► 장부별 필터·VET ──► jobs.jsonl ──► [Mac] Claude CLI 판단 ──► results.jsonl
                                     ▲  Helius/RPC/RugCheck(보유자)          │
                                     ▲  GeckoTerminal 1분봉(D만)              ▼
World Monitor Redis ──► regime_context(매크로 블록, 참고용) ──► 판단 프롬프트   [박스] finish: 장부별 매수 규칙 → SIZE → FILLS → RISK → 장부별 매도
```
- 진입점: `desk/manual/variants.sh` → `desk/manual/run_variants.py` (`prepare` / `finish`).
- 장부는 서로 독립이다. 같은 원시 데이터(스캔, 보유자 조회, 가격)를 사이클 안에서 공유하고(메모이즈), 판단·잔고·포지션은 장부마다 따로다. → [paper-books.md](paper-books.md)
- 단계별 명령과 장애 처리 → [runbook.md](runbook.md)

## 박스와 Mac의 역할
| 위치 | 하는 일 | 경로 |
|---|---|---|
| 박스 (Linux, Grok Bot 작업 머신) | 데스크 실행, 장부 DB, 셀프호스팅 World Monitor, 15분 루틴 | `/workspace/desk`, `/workspace/worldmonitor` |
| Mac (사용자 `minsu`) | Claude CLI(구독 로그인)로 판단 작업 실행, 이 git 저장소 | `/Users/minsu/workspace/Personal/worldmonitor-bot` |

- 박스의 `/workspace/desk`와 이 저장소의 `desk/`는 같은 코드다(git 이력은 따로). 이 저장소가 GitHub(`minsuRob/worldmonitor-bot`)에 올라가는 쪽이다.
- 판단 작업 파일은 박스 `/workspace/worldmonitor/data/claude-cli/<runId>/jobs.jsonl`에 생기고, Mac `claude-cli-runs/<runId>/`로 복사돼 실행된 뒤 `results.jsonl`이 다시 박스로 돌아온다. 복사는 Grok Bot 루틴이 하며, 루틴이 따를 기준 정의는 [`desk/manual/ROUTINE.md`](../../desk/manual/ROUTINE.md)다(복사 방법 자체는 아직 기존 루틴과 대조하지 않았다).
- `finish`는 박스 World Monitor의 `scripts/claude-cli/import-results.mjs`로 결과를 가져온다(`stored.jsonl` 생성).

## Claude CLI 러너 (Mac)
- 파일: `desk/manual/mac/claude_cli_runner.sh` (git 추적, 2026-10-29부터 정본). 예전 사본인 Mac `tools/claude_cli_runner.sh`와 World Monitor 쪽 `tools/claude-cli/claude_cli_runner.sh`는 추적되지 않으며, 루틴이 새 경로로 바뀌면 지운다.
- 기록: 작업마다 `claudeModel`(CLI가 보고한 실제 모델), `requestedModel`/`requestedEffort`(env 값, 없으면 `null`). `results.meta.json`에도 요청값. 모델·노력 수준은 고정하지 않는다.
- 비용 안전장치: `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`을 지워서 **구독 로그인만** 쓴다. `ANTHROPIC_BASE_URL`은 anthropic.com일 때만 유지. MCP 서버 없음, 도구 없음.
- 환경 변수: `CLAUDE_CLI_MODEL`, `CLAUDE_CLI_EFFORT`, `CLAUDE_CLI_MAX_JOBS`(기본 20, 데스크는 40으로 맞춰 씀), `CLAUDE_CLI_TIMEOUT`(기본 300초).
- 출력: `results.jsonl`, `results.meta.json` (작업 파일과 같은 폴더).

## 데이터 출처 (모두 공개·읽기 전용)
| 출처 | 용도 | 코드 |
|---|---|---|
| DexScreener `api.dexscreener.com` | 스캔, 가격, 유동성, 거래량, RISK 측정 | `config.DEX`, `bots.scan_fetch`, `bots.risk_measure` |
| Helius RPC (무료 플랜) | 최대 보유자(`getTokenLargestAccounts`), 보유자 수(DAS `getTokenAccounts`) | `config.HELIUS_*`, `bots.holder_count_helius` |
| 공용 Solana RPC | Helius 다음 대체 경로 | `config.SOLANA_RPCS` |
| RugCheck `api.rugcheck.xyz` | 모든 RPC가 막혔을 때 최대 보유자 대체 | `bots.top_holders_rugcheck` |
| GeckoTerminal 1분봉 | D장부 30분 급등 추격 금지 검사 | `book_rules.fetch_ohlcv_1m` |
| World Monitor Redis (셀프호스팅) | 매크로 블록(BTC, VIX, 분위기, WTI, 헤드라인) | `manual/regime_context.py` |
| World Monitor API `localhost:3000` | READY 체크 3개, BOOK 예측시장 목록 (상시 데스크용) | `config.WM_CHECKS`, `chief.run_checks` |
| Kalshi, Polymarket gamma | BOOK 가격 (상시 데스크용) | `config.KALSHI`, `config.GAMMA` |

- Helius 한도: 표준 RPC 8 rps로 제한(`HELIUS_RPS`), DAS 2 rps(`HELIUS_DAS_RPS`), DAS 하루 20,000 크레딧 예산(`HELIUS_DAS_DAILY_CREDITS`), 토큰당 최대 5페이지.
- GeckoTerminal: 0.45 rps(`GT_RPS`), D의 다른 검사를 모두 통과한 후보에만 호출.
- 매크로 블록은 **참고용**이다. VET, SIZE, RISK 규칙에는 영향이 없다. 6시간보다 오래된 값은 `unavailable`로 표시된다.

## 두 가지 실행 모드
1. **15분 장부 사이클** (현재 사용): `manual/variants.sh`. 프로세스를 상주시키지 않고 루틴이 한 번씩 부른다.
2. **상시 데스크** (`start.sh` → `chief.py`가 6개 봇 프로세스 실행): 코드는 있지만 2026-10-28 이후 가동하지 않았다. → [desk-bots.md](desk-bots.md)
