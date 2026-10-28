# 현재 상태 (2026-10-28 21:23 KST 기준)

**데스크는 시작하지 않음.** 봇·CHIEF 프로세스 없음, 모의 거래 0건(주문·체결·베팅·포지션 0).
박스 내부 커밋: `46c4f644cf1d8033f1d24caa4281f010691a4c7c` (이 패키지는 그 코드를 정리한 것).

## 체크 결과 (curl로 실측, 21:23 KST)
| 체크 | HTTP | 시간 | 결과 |
|---|---|---|---|
| fear-greed (self-hosted) | 200 | 9.4 ms | compositeScore 55.7 "Neutral" |
| prediction markets (self-hosted) | 200 | 6.0 ms | dataAvailable true, 시장 1개(page_size=1) |
| cross-source signals (self-hosted) | 200 | 3.6 ms | 신호 8개 |
| DexScreener `search?q=BONK` | 200 | 62.8 ms | `pairs` 포함(30개) |
| Kalshi open markets | 200 | 227.8 ms | 시장 100개 |
| Polymarket gamma (앞선 테스트) | 200 | 129.9 ms | 시장 50개 |

참고: cross-source는 처음엔 503이었고, 키 없는 시더(지진·기상특보·방사선·규제·제재·사이버위협·시장·원자재)를 돌려 25개 소스 키 중 11개를 채운 뒤 200이 됨.

## 왜 READY가 아닌가
- 데스크가 실행 중이 아님(사용자 지시로 모의 매매 시작 보류) → 봇 하트비트 조건 불충족.
- WM 시드 데이터는 TTL이 있고 주기 갱신이 아직 없음 → 체크가 시간이 지나면 다시 비거나 오류가 날 수 있음.

## 아직 안 된 것
1. 시드 데이터 주기 갱신(cron 등) 없음.
2. BOOK의 자체 확률은 WM forecast에서 오는데, forecast는 AI(LLM) 키가 필요 → 없으면 `NO_MODEL_PROB` 기록, 예측 베팅 없음.
3. DexScreener가 홀더 수를 주지 않음 → VET ③은 평가 불가, 해당 후보는 PASS_PARTIAL.
4. 밈코인 Kelly 입력값은 가정값(승률 45%, 손익비 1.5).
5. VET ⑤(단일 출처 뉴스)는 아직 확인 수단 없음.
6. 가이드에 손절·익절·최대 보유 시간이 없어 추가하지 않음.
7. 공용 Solana RPC 속도 제한(429) → VET 거절이 늘 수 있음.

## 키·가입·결제가 필요한 항목 (진행하지 않음)
| 서비스 | 필요한 것 | 비고 |
|---|---|---|
| FRED, EIA, NASA FIRMS, ACLED, Finnhub, Alpha Vantage, AviationStack, AISStream | 무료 가입 후 키 | 여러 개가 cross-source 누락 소스(14개)에 해당 |
| OpenRouter 또는 다른 LLM 키 | 키 | forecast(BOOK 자체 확률)에 필요 |
| GIE/AGSI, UN Comtrade, WTO, OTX, OpenAQ, WAQI, USDA FAS, IMF, UCDP, SAM.gov | 키 | 가격 미확인 |
| OpenSky | 계정 | 제한적 무료 |
| Cloudflare Radar (인터넷 장애) | 토큰 | 문서상 유료 |
| World Monitor 호스팅 API 키 | Pro 플랜 | 셀프호스팅이면 불필요 |
