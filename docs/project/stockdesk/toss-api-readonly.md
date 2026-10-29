# 토스 Open API — 시세 조회 전용

[← 인덱스](../../../CLAUDE.md) · 코드: `stockdesk/quotes.py`(`TossQuotes`, `TOSS_ENDPOINTS`, `ALLOWED_PATHS`, `FORBIDDEN_WORDS`, `SYMBOL_RE`, `RateLimiter`), `stockdesk/config.py`(`TOSS_*`), `stockdesk/marketdb.py`(`KVStore` 토큰 캐시), `stockdesk/manual/toss_smoke.py`(실호출 점검), `stockdesk/manual/tests/test_toss_readonly.py`

## 선언
**주문·계좌 API는 구현하지 않는다.** 이 데스크는 모의 매매만 하고, 토스증권 Open API는 **시세·종목 정보·시장 정보·랭킹 조회**에만 쓴다. 토스에는 모의투자 모드가 없으므로 "모의로라도 주문을 보내는" 경로는 존재하지 않는다 — 모의 장부는 데스크가 `state/books/*.db`에 스스로 기록한다(루트 `CLAUDE.md` 절대 규칙 5).

**쓰지 않고, 앞으로도 구현하지 않는 엔드포인트**: `/accounts`, `/holdings`, `/orders*`, `/conditional-orders*`, `/buying-power`, `/sellable-quantity`, `/commissions`.

## 공식 스펙 (2026-10-29 Mac(허용 IP)에서 실호출로 확인)
- 출처: `https://openapi.tossinvest.com/openapi-docs/latest/openapi.json`, `overview.md`, 목차 `https://developers.tossinvest.com/llms.txt`.
- 응답 봉투: 성공 `{"result": ...}`, **숫자는 모두 문자열**(`quotes._f`로 변환), 오류 `{"error": {code, message, requestId}}`, 429에 `Retry-After`.
- 데스크가 쓰는 엔드포인트(토큰만 POST, 나머지 GET)와 응답 처리 → [data-sources.md](data-sources.md#토스-엔드포인트-공식-스펙)

## 어떻게 강제되는가
| 층 | 내용 |
|---|---|
| 엔드포인트 표 | `TOSS_ENDPOINTS`에 `token`(POST)과 조회 GET(`prices`, `candles`, `stocks`, `warnings`, `investor_flow`, `rankings`, `exchange_rate`, `calendar_kr`, `calendar_us`)만 있다. `ALLOWED_PATHS`는 이 표의 경로(템플릿 `{symbol}` 포함)에서 자동으로 만든다 |
| `TossQuotes._get` | 요청 전 `assert`: 메서드 `GET`만; 경로가 `ALLOWED_PATHS` 안; 경로(소문자)에 `FORBIDDEN_WORDS`(`order`, `account`, `holding`, `balance`, `buying-power`, `sellable`, `commission`, `cancel`, `deposit`, `withdraw`, `transfer`, `conditional`) 없음; `{symbol}`은 `SYMBOL_RE` `^[A-Za-z0-9.-]{1,20}$`를 통과한 값만 치환; 쿼리 값은 `^[A-Za-z0-9.,:+-]{0,4000}$`만 |
| 헤더 | `Authorization: Bearer <token>`만. 계좌 범위 헤더(`X-Tossinvest-Account`)를 보내지 않는다 |
| 클라이언트 표면 | 원시 조회 메서드(`prices`, `candles`, `stocks`, `warnings`, `investor_flow`, `rankings`, `exchange_rate`)와 `screen.py` 계약용(`quote`, `daily_bars`, `minute_bars`, `ranking`, `stock_flags`, `stock_flags_many`, `fx_rate`)뿐 |
| 테스트 | `test_toss_readonly.py`(가짜 HTTP): 표면·경로에 금지 단어 없음, `quotes.py`에 주문·계좌 경로 문자열·계좌 헤더 없음, 주문 경로·POST를 `_get`이 거부, 응답 매핑(문자열→숫자, `changeRate` 비율→%, 봉 역순 정렬, 플래그 매핑), 토큰 캐시·401 재발급·429 재시도, 레이트리미터, `api.worldmonitor.app` 거부 |
| 공통 HTTP | `common.http_json`/`http_text`는 `api.worldmonitor.app`을 `assert`로 거부 |

주문·계좌 코드를 넣으려는 변경은 이 테스트가 떨어지고, 리뷰에서 거부한다.

## 토큰: 클라이언트당 하나
- OAuth2 client credentials(`POST /oauth2/token`, form). **유효 토큰은 클라이언트당 하나뿐이고, 새로 발급하면 이전 토큰이 무효가 된다.**
- 그래서 토큰을 `state/market.db`의 `kv`(`marketdb.KVStore`, 키 `toss_token`)에 캐시해 `prepare`·`finish`·cron `slot`·`toss_smoke.py`가 **같은 토큰을 공유**한다. 만료 `TOSS_TOKEN_MARGIN_S` 60초 전에만 갱신하고, 401이면 한 번 재발급 후 재시도.
- **주의: 같은 client_id로 다른 머신(예: Mac)에서 손으로 실행하면 그쪽이 새 토큰을 받아 박스의 토큰이 무효가 된다.** 박스는 다음 호출에서 401 → 재발급으로 회복하지만, 두 머신이 번갈아 돌면 서로 계속 무효화한다. 박스가 운영 중이면 다른 머신에서 실호출하지 않는다.
- 토큰 값은 `market.db`(git 제외)에만 있고 로그·출력에 찍지 않는다.

## 키 발급과 허용 IP (사용자 작업)
- 토스증권 **설정 → Open API**에서 앱을 만들고 `client_id`/`client_secret`을 받는다.
- **허용 IP**에 실행 머신의 공인 IP를 등록해야 토큰·시세 호출이 통과한다. 2026-10-29 실호출은 Mac(등록된 IP)에서 했다. **박스에서 돌리려면 박스 공인 IP를 추가해야 한다.** IP가 바뀌면 다시 등록한다.
- 점검: `cd stockdesk && python3 manual/toss_smoke.py [KRX코드] [US코드]`(기본 005930, AAPL) — 토큰, KRX/US 시세, 일봉, 랭킹, 플래그, 투자자별 수급, 환율을 읽기 전용으로 한 번씩 호출한다. 새 토큰을 강제로 받지 않으며 키·토큰을 찍지 않는다. 단위 테스트가 아니다(실호출, 허용 IP 필요).

## 비밀 저장 (이름만 문서화, 값은 어디에도 쓰지 않음)
| 이름 | 용도 | 위치 |
|---|---|---|
| `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` | 토스 Open API 토큰 | `stockdesk/.env`(git 제외, 권한 600 권장) 또는 환경 변수. `config._load_env_file`이 읽고, 이미 있는 env가 우선 |
| `DART_API_KEY` | DART 공시(DT·TH) | 같음 |
| `FINNHUB_API_KEY` | US 실적 캘린더(ER-US). **현재 비어 있음 → ER-US 후보 없음** | 같음 |

- 템플릿: `stockdesk/.env.example`(git 추적, 값 비어 있음). `.gitignore`: `.env`, `.env.*`(`.env.example` 제외), `*.key`, `state/`, `logs/`.
- 자격 증명이 없어도 데스크는 돈다: `get_source("toss")`가 `None`이면 KRX fetch는 건너뛰고(`snapshot_source: "none"`), US는 Stooq·er-api로 봉·환율만 받는다.

## 레이트리미터
| 그룹 | 공개 한도(초당, `overview.md`) | `config.TOSS_RPS`(× 0.8) | 쓰는 엔드포인트 |
|---|---|---|---|
| `AUTH` | 5 | 4.0 | token |
| `STOCK` | 5 | 4.0 | stocks, warnings |
| `STOCK_TRADING_TREND` | 10 | 8.0 | investor-trading |
| `MARKET_INFO` | 3 | 2.4 | exchange-rate, market-calendar |
| `MARKET_DATA` | 15 | 12.0 | prices |
| `MARKET_DATA_CHART` | 20 | 16.0 | candles |
| `RANKING` | 5 | 4.0 | rankings |

- `RateLimiter.wait(group)`: 그룹별로 `1/rps` 간격(스레드 안전). 429 → `TOSS_429_WAIT_S` 1초 쉬고 한 번 재시도(`http_json`이 헤더를 주지 않아 `Retry-After`는 읽지 않음). 401 → 토큰 재발급 1회.
- `warnings`는 종목마다 1회(STOCK 5/s)라 **랭킹 종목 + 보유 종목만** 조회한다(나머지는 `stocks`의 플래그만).
- 실측(2026-10-29, 첫 실데이터 `krx_after` 스냅샷): **103초, 토스 호출 467회**. 처음 보는 종목은 일봉 300개를 받기 때문이고, 다음 실행부터는 종목당 3봉만 받아 줄어든다. 일일 한도는 문서에서 확인하지 못했다.
- `TossQuotes.calls`가 프로세스 안 호출 수를 센다.
