# 용어집

[← 인덱스](../../CLAUDE.md)

| 용어 | 뜻 | 어디 |
|---|---|---|
| 장부 (book) | 독립된 $1,000 모의 계좌. BASE·A·B·C·D | [paper-books.md](paper-books.md) |
| 사이클 / `runId` | 15분 한 번의 `prepare`→판단→`finish`. `meme-var-YYYYMMDD-HHMMSS` | [runbook.md](runbook.md) |
| `p_win` | Claude가 낸 "약 24시간 안에 손실보다 이익에 먼저 닿을 확률" | `run_variants.SYSTEM` |
| `payoff_ratio` (b) | 평균 이익 / 평균 손실 | `run_variants.SYSTEM` |
| EV | `p_win × b − (1 − p_win) − 0.03` (0.03 = 왕복 비용 `ROUNDTRIP_COST`). A·C는 EV > 0이면 매수 | `book_rules.ev_of` |
| 거부권 (veto) | D장부: 수치 신호로 사고, Claude는 러그 위험일 때만 막음 | `book_rules.D_SYSTEM` |
| Kelly 상한 | `p − (1−p)/b`를 6%(`KELLY_CAP`)로 자름. 입력 p=0.45, b=1.5는 **가정값** | `bots.planned_meme_order` |
| 고정 비율 | C 10%, D 5% (`SIZE_FIXED_FRACTION`) | `book_rules.OVERRIDES` |
| 묶인 현금 (encumbered) | 아직 체결되지 않은 주문에 잡힌 돈 | `common.encumbered` |
| `PASS_PARTIAL` | VET 통과지만 일부 검사(보유자 증가 비교 등)를 할 수 없었음 | `bots.vet_one` |
| `run30` | 최근 30분 안 (저점 → 그 뒤 고점) 최대 배수. D는 ≥2.5면 거절 | `book_rules.run_multiple` |
| vol_accel | `volume.m5 × 12 / volume.h1` | `book_rules.precheck` |
| vol ratio | `volume.h6 / (volume.h24 / 4)`. <0.20이면 RISK 청산 | `bots.risk_cycle` |
| READY | WM 체크 3개 실제 데이터 + DexScreener 정상 + 봇 하트비트 + 중단 아님 | [desk-bots.md](desk-bots.md) |
| degraded / halted | WM 체크 실패(BOOK만 쉼) / 같은 봇 1시간 2회 사망(데스크 중단, RISK는 계속) | `chief.py` |

## 거절·판단 코드
| 코드 | 뜻 |
|---|---|
| `0_already_held` | 이 장부가 이미 보유 중 |
| `1_top_holder` … `7_young_shrinking_liq` | VET 공통 검사 → [desk-bots.md](desk-bots.md#vet-7개-검사-botsvet_one) |
| `C_*`, `D_*` + `_quote_not_sol`, `_age`, `_no_momentum`, `_collapsing`, `_sell_pressure`, `_inactive`, `_buy_ratio`, `_no_accel`, `_few_holders`, `_run30_ge_2.5x`, `_run30_unknown` | 장부별 사전·사후 검사 (`book_rules.precheck`/`postcheck`/`run30_check`) |
| `NO_JUDGE` / `JUDGE_UNPARSEABLE` / `OVER_JOB_CAP` | Claude 결과 없음 / 해석 불가 / 작업 상한 초과 → SKIP |
| `UNMEASURABLE`, `VOL_RATIO<0.20`, `FLAG_MCAP_+60` | 공통 RISK |
| `ZERO` | SIZE 결과 0 (최소 주문 $30 미만, 최대 보유 수, 수수료 >2%) |
