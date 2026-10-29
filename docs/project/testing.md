# 테스트

[← 인덱스](../../CLAUDE.md) · 위치: `desk/manual/tests/`

모든 테스트는 `desk/`에서 실행한다. 네트워크 없이 도는 것은 실제 장부를 건드리지 않는다.

| 파일 | 무엇을 | 실행 | 비고 |
|---|---|---|---|
| `test_books_v2.py` | 장부별 오버라이드, C/D 사전·사후 검사, EV/거부권 매수 규칙, 고정 비율 크기, 최대 보유 수, 손절·부분 익절·추적 손절 | `python3 manual/tests/test_books_v2.py` | 임시 복사본, 네트워크 없음 |
| `test_d_entry_filters.py` | D 호가 토큰 필터, 30분 급등(2.8배 거절 / 1.5배 통과), 1분봉 실패 시 거절, 토큰 "0" 재현 | `python3 manual/tests/test_d_entry_filters.py` | 임시 복사본, 네트워크 없음 |
| `test_regime.py` | 매크로 블록 형식·길이·오래된 값 처리 | `python3 manual/tests/test_regime.py` | 박스 경로 `/workspace/desk` 기준 |
| `test_lock.sh` | `prepare`/`finish` 동시 실행 시 종료 코드 3 | `bash manual/tests/test_lock.sh` | **실제** `state/variants.lock` 사용. 루틴과 겹치지 않을 때만 |
| `test_indep.py`, `test_indep_finish.py` | 장부 독립성(공유 데이터, 장부별 결정) 드라이런 | 직접 실행 | 박스 임시 경로(`/tmp/deskdry2` 등)에 묶인 작업용 스크립트 |
| `dry_regime.py` | 매크로 블록 드라이런 | 직접 실행 | 작업용 스크립트 |

## 규칙
- 장부 규칙(`book_rules.py`)이나 `bots.py`를 바꾸면 위 두 개(`test_books_v2.py`, `test_d_entry_filters.py`)를 반드시 돌리고 결과(통과 수)를 보고한다. 통과 수는 실행 출력에서 그대로 옮긴다.
- 새 테스트는 실제 `state/`가 아니라 임시 복사본과 가짜 응답(네트워크 없음)을 쓴다.
- `analysis/` 아래 스크립트(예: `d_cadence_0/simulate.py`)는 분석 재현용이지 테스트가 아니다.
