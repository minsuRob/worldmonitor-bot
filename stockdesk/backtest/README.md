# backtest — 일봉 백테스트 (모의, 읽기 전용)

[← stockdesk](../README.md)

실제 장부와 **같은 전략 스크린(`strategies/*.py`)과 같은 체결·비용 모델(`fills.py`)**로 과거 일봉을 다시 돌린다. 장부를 돌리기 전에 "이 규칙이 비용을 넘는 수익을 냈는지"를 먼저 본다.

```bash
cd stockdesk
python3 backtest/bt.py MO 2026-01-02 2026-10-29          # state/market.db 의 일봉·수급으로
python3 backtest/bt.py CB 2026-08-03 2026-10-29 --fake   # 합성 시장(코드 동작 확인용, 숫자에 의미 없음)
```
출력: 한 줄 JSON `{book, from, to, days, start, end, return_pct, mdd_pct, trades, win_rate, open_at_end, data}`.

## 지원 범위
| 장부 | 지원 | 비고 |
|---|---|---|
| FL, MO, MO-US, EV | 예 | 숫자 규칙만. FL은 `flow_daily`, EV는 `calendar`가 있어야 매매가 생긴다 |
| CB | 근사 | 15:00 장중 랭킹 대신 **그날 일봉**(종가·거래대금)으로 스크린, 종가에 사서 다음 시초가에 판다. Claude 거부권은 건너뜀(=모두 통과) |
| DT, TH, ER-US | 아니오 | LLM 판단이 필요하다 |

## 한계
- `--fake`는 결정적 합성 데이터다. 수익률 숫자는 **코드가 도는지만** 보여 준다.
- 실제 데이터는 `state/market.db`에 쌓인 만큼만 쓴다(장부를 돌리면 슬롯마다 쌓인다). 과거를 길게 보려면 일봉을 먼저 채워야 한다(출처 TBC → [data-sources](../../docs/project/stockdesk/data-sources.md)).
- 동시호가 거래대금이 없으면 `ASSUMED_CLOSE_AUCTION_SHARE`(가정)로 상한을 잡는다.
- `DataView`는 시뮬레이션 날짜 이후 행을 돌려주지 않는다(룩어헤드 차단). 단, 유니버스는 현재 목록을 쓰므로 **생존 편향**이 있다.
