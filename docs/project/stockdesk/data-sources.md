# 데이터 출처 (모두 읽기 전용)

[← 인덱스](../../../CLAUDE.md) · 코드: `stockdesk/quotes.py`(어댑터), `stockdesk/screen.py`(`_refresh_universe_krx`, `_fetch_krx`, `_fetch_us`, `_fetch_dart` → `market.db`), `stockdesk/marketdb.py`(스키마), `stockdesk/config.py`(URL·한도), `stockdesk/data/`(정적 파일)

슬롯마다 `screen.shared_snapshot`이 **한 번** 가져와 `state/market.db`에 쓰고, 모든 장부는 `Snapshot`으로 DB만 읽는다(`asof` = 슬롯 날짜, 미래 데이터 없음). 모든 행에 `source`(toss / dart / stooq / erapi / finnhub / fake / config)가 있어 보고서가 숫자 출처를 말할 수 있다.

## 토스증권 Open API — 주 출처, 조회만
- 출처: `openapi.tossinvest.com/openapi-docs/latest/openapi.json`, `overview.md`, 목차 `developers.tossinvest.com/llms.txt`. **2026-10-29 Mac(허용 IP)에서 실호출로 확인.**
- 봉투: 성공 `{"result": ...}`, 숫자는 모두 문자열, 오류 `{"error": {code, message, requestId}}`.
- 안전장치(GET만, `ALLOWED_PATHS`, `FORBIDDEN_WORDS`, `SYMBOL_RE`, 쿼리 검증, 계좌 헤더 없음), 토큰 1개 규칙, 허용 IP, 레이트 한도 → [toss-api-readonly.md](toss-api-readonly.md)
- 자격 증명이 없으면 `get_source("toss")`는 `None`이고 KRX fetch는 건너뛴다(`snapshot_source: "none"`; KRX 장부 후보 없음, 보유 포지션은 RISK stale 규칙). US는 Stooq·er-api로 봉·환율만.

### 토스 엔드포인트 (공식 스펙)
| 이름 | 메서드·경로 | 그룹 | 파라미터 → 데스크가 쓰는 필드 | 데스크 용도 |
|---|---|---|---|---|
| `token` | `POST /oauth2/token` | AUTH | form `grant_type=client_credentials`, `client_id`, `client_secret` → `access_token`, `expires_in` | 공유 토큰(`market.db.kv`) |
| `prices` | `GET /api/v1/prices` | MARKET_DATA | `symbols`(≤200, 콤마) → `symbol`, **`lastPrice`만**, `timestamp`, `currency` | 랭킹 밖 유니버스·보유 종목 현재가(KRX), US 전 종목 현재가 |
| `candles` | `GET /api/v1/candles` | MARKET_DATA_CHART | 쿼리 `symbol`, `interval`(1d\|1m), `count`(≤200), `before`(포함) → `candles[{timestamp, openPrice, highPrice, lowPrice, closePrice, volume}]`, `nextBefore`. **최신순** → 데스크가 뒤집어 오래된 순으로. **거래대금 없음** → `screen._norm_bars`가 `turnover = close × volume` | 일봉: 처음 보는 종목 300개, 이후 3개(당일 봉은 마감까지 덮어씀). 현재가 스냅의 open/high/low/volume 보충(`_fill_from_bars`) |
| `stocks` | `GET /api/v1/stocks` | STOCK | `symbols`(≤200) → `name`, `market`, `securityType`, `status`, `sharesOutstanding`, `koreanMarketDetail{krxTradingSuspended, liquidationTrading}` | KRX 유니버스 이름·종류(ETF/STOCK)·시장·시총(= 발행주식 × 현재가); 플래그 |
| `warnings` | `GET /api/v1/stocks/{symbol}/warnings` | STOCK | → `[{warningType, startDate, endDate}]`(오늘이 기간 안인 것만) | 플래그. **랭킹 종목 + 보유 종목만**(STOCK 5/s) |
| `investor_flow` | `GET /api/v1/stocks/{symbol}/investor-trading` | STOCK_TRADING_TREND | KR만, `count`(≤100) → `records[{date, foreigner/institution/individual{netBuyVolume}}]` — **투자자별 순매수 수량(주)** | `krx_after`: 유니버스·보유 종목(STOCK만) 5일 → 그날 종가 × 수량 = 금액 → `flow_daily`. **FL 장부의 데이터 출처** |
| `rankings` | `GET /api/v1/rankings` | RANKING | `type`, `marketCountry`(KR/US), `duration`, `count`(≤100), `excludeInvestmentCaution` → `rankedAt`, `rankings[{rank, symbol, price{lastPrice, basePrice, changeRate}, tradingVolume, tradingAmount}]`. **`changeRate`는 비율** → %로 저장 | `MARKET_TRADING_AMOUNT` `realtime` 100 = KRX 스냅(CB·TH); `MARKET_TRADING_AMOUNT` `1mo` 상위 `KRX_UNIVERSE_TOP` 100 = KRX 유니버스(하루 1회); `TOP_GAINERS` `1d`(`change_pct` 키) |
| `exchange_rate` | `GET /api/v1/exchange-rate` | MARKET_INFO | `baseCurrency=USD`, `quoteCurrency=KRW` → `rate`, **`midRate`**, `validFrom` | `fx_daily` 마크(매매기준율 `midRate`, 없으면 `rate`) |
| `calendar_kr`, `calendar_us` | `GET /api/v1/market-calendar/KR`, `/US` | MARKET_INFO | — | 허용 목록에만 있고 호출하지 않음(휴장일은 `data/holidays_*.json`) |

### KRX 유니버스 (`screen._refresh_universe_krx`, 하루 1회)
- `rankings` `MARKET_TRADING_AMOUNT` `1mo` 상위 `KRX_UNIVERSE_TOP` 100 + 보유 종목 → `stocks`로 이름·종류·시장·발행주식.
- `mcap = sharesOutstanding × 랭킹 lastPrice`, `avg_turnover = 1mo tradingAmount / KRX_UNIVERSE_TURNOVER_DAYS`(21, ASSUMED). 이후 전략의 `universe_filter`가 `KRX_MIN_MCAP_KRW` 3000억(ASSUMED)·`KRX_MIN_AVG_TURNOVER_KRW` 50억(ASSUMED)으로 거른다.
- `kv.universe_day:KRX`에 날짜를 적어 같은 날 다시 받지 않는다.

### 플래그 매핑 (`stocks` + `warnings` → `config.HALT_FLAGS`/`BAN_FLAGS` 이름)
| 토스 | 데스크 플래그 | 효과 |
|---|---|---|
| `koreanMarketDetail.krxTradingSuspended` | 거래정지 | RISK: 포지션 HALTED; 금지 |
| `koreanMarketDetail.liquidationTrading`, `warningType=LIQUIDATION_TRADING` | 정리매매 | RISK: 청산; 금지 |
| `status = DELISTED` | 상장폐지 | RISK: 청산; 금지 |
| `INVESTMENT_RISK` | 투자위험 | RISK: 청산; 금지 |
| `INVESTMENT_WARNING` | 투자경고 | 금지 |
| `OVERHEATED` | 단기과열 | 금지 |
| `VI_*` | (무시) | — |
| — | **관리종목, 불성실공시: 출처 없음** | 토스 API에 없다. `HALT_FLAGS`의 관리종목 청산과 `BAN_FLAGS`의 불성실공시는 실데이터에서 발동하지 않는다 |

### 토스에 없는 것
| 항목 | 결과 |
|---|---|
| 동시호가(종가 단일가) 거래대금 | `auction_turnover`는 항상 `None` → CB 동시호가 체결은 늘 `ASSUMED_CLOSE_AUCTION_SHARE`(당일 거래대금의 8%) 경로(`liquidity_ref="assumed"`) → [fill-and-cost-model.md](fill-and-cost-model.md) |
| 일봉 거래대금 | `close × volume`으로 계산(`_norm_bars`) — 실제 거래대금과 다를 수 있다 |
| US 장 마감 후 실적 캘린더 | ER-US는 Finnhub(`FINNHUB_API_KEY`)가 필요. **키가 비어 있어 현재 ER-US 후보 없음** |
| 지수 편입·보호예수 해제 캘린더 | 출처 미구현(fake만) → EV 매수 없음, 보호예수 금지 창 비어 있음 |
| 관리종목·불성실공시 | 출처 없음(위 표) |

### 실측 (2026-10-29)
- 첫 실데이터 `krx_after` 스냅샷: **103초, 토스 호출 467회**(처음 보는 종목마다 일봉 300개). 이후 실행은 종목당 3봉만 받는다.
- 실호출 점검 스크립트: `cd stockdesk && python3 manual/toss_smoke.py [KRX코드] [US코드]`(읽기 전용, 공유 토큰 사용, 허용 IP 필요).

## 보조 어댑터 (`quotes.py`)
| 어댑터 | 출처 | 상태 | 키 | 쓰는 곳 |
|---|---|---|---|---|
| `DartOpen` | `opendart.fss.or.kr/api/list.json` (당일 공시 전체, 페이지 100×최대 10) | **2026-10-29 실호출 확인**(형식 일치) | `DART_API_KEY`, 없으면 건너뜀 | `krx_after`에서 `disclosures`(DT·TH) |
| `FinnhubEarnings` | `finnhub.io/api/v1/calendar/earnings` | TBC | `FINNHUB_API_KEY`(현재 비어 있음) | `earnings`(ER-US), `us_close`/`us_er` |
| `UsDailyBars` | Stooq 일봉 CSV `stooq.com/q/d/l/?s=<sym>.us&i=d` | TBC(비공식, 일일 호출 상한) | 없음 | US 일봉, **토스 자격 증명이 없을 때만** |
| `FxPublic` | `open.er-api.com/v6/latest/USD` → `rates.KRW` | TBC(비공식 무료) | 없음 | `fx_daily`, 토스 환율 실패 시(`us_close`/`us_er`) |
| World Monitor Redis | 셀프호스팅 WM(`UPSTASH_REDIS_REST_URL/TOKEN` 또는 `/workspace/worldmonitor/.env.local`) | 키 이름 TBC(`market:indices:v1`의 KOSPI/SPX/USDKRW 등) | — | `regime_context` 매크로 블록(참고용, 6시간 지나면 `unavailable`) |

`api.worldmonitor.app`은 `common.http_json`/`http_text`가 `assert`로 거부한다.

## `state/market.db` 테이블 (`marketdb.MARKET_SCHEMA`)
| 테이블 | 키 | 내용 | 채우는 슬롯/출처 |
|---|---|---|---|
| `bars_daily` | (market, code, date) | OHLCV + `turnover`(= 종가×거래량) | 모든 슬롯, 스냅+보유 종목; toss / stooq / fake |
| `intraday_snap` | (slot_date, slot, market, code) | `price, open, high, low, change_pct, volume, turnover, auction_turnover(None), high20` | 모든 슬롯; KRX = 실시간 거래대금 랭킹 100 + 유니버스·보유 `prices`; US = 유니버스+보유 `prices`; 빈 값은 당일 봉에서 보충 |
| `flow_daily` | (market, code, date) | 외국인·기관·개인 순매수 **금액**(수량 × 그날 종가) | `krx_after`; toss / fake |
| `disclosures` | `rcept_no` | DART 공시 + `judged_books` | `krx_after`; dart / fake |
| `calendar` | id | `event_type`(INDEX_ADD, LOCKUP_EXPIRY), 발표일·효력일, 금지 창 | **미구현**(fake만) |
| `flags` | (market, code, date) | 플래그 목록 JSON | KRX 슬롯; toss(`stocks` 스냅 전 종목, `warnings` 랭킹+보유) / fake |
| `fx_daily` | date | KRW/USD, `source` | KRX 슬롯(toss), `us_close`/`us_er`(toss → erapi); 없으면 `config` 1400 |
| `universe` | (market, code) | 이름·`instrument`·`sector`(KRX는 시장명)·시총·평균 거래대금 | KRX: 하루 1회(위 절); US: `data/us_universe.json` 시드 |
| `earnings` | (market, code, date) | EPS·매출 추정/실제, `when_` | `us_close`/`us_er`; finnhub / fake |
| `slot_runs` | (slot, day) | `run_id`, `phase` | `due` 중복 방지 → [schedule.md](schedule.md) |
| `kv` | k | `toss_token`(공유 토큰), `universe_day:KRX` | `quotes`/`screen` |

## `data/` 정적 파일 (git 추적)
| 파일 | 내용 | 관리 |
|---|---|---|
| `holidays_KRX_2026.json`, `holidays_US_2026.json` | 연도별 휴장일 `dates` | **수동**(TBC). 없는 연도는 주말만 쉼. 토스 `market-calendar`는 아직 쓰지 않음 |
| `us_universe.json` | S&P500 + Nasdaq100 **일부** 시드 | 수동, 분기 갱신 TBC. `market.db.universe`가 비어 있을 때만 로드 |
| `corp_code.json` | DART `stock_code → corp_code` 맵(비어 있음) | 선택. `list.json`이 `stock_code`를 주므로 현재 불필요 |

## FAKE_SNAPSHOT (오프라인·테스트)
`STOCKDESK_FAKE_SNAPSHOT=1`이면 `screen.fake_market`이 HTTP 없이 결정적 합성 시장을 `market.db`에 쓴다(`source="fake"`): KRX 40종목(`가상00~39`, 39번은 ETF), US는 `us_universe.json` 종목, 320거래일 일봉, 30일 수급, 플래그(`관리종목`·`투자경고` 1개씩), 보호예수 해제·지수 편입 캘린더 1건씩, 공시 1건, 환율 1400, US 실적 1건(`us_er`에서 첫 종목 +6% 애프터마켓), 동시호가 거래대금 = 당일의 10%. 테스트 하네스는 항상 이 모드로 임시 복사본에서 돈다. **실운영 `state/`에서는 켜지 않는다**(fake 행이 섞임).
