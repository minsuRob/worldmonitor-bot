# 작업 규칙

[← 인덱스](../../CLAUDE.md)

## 금지 (사용자 지정)
- 실제 주문, 지갑, 서명 키, 거래소 로그인, 결제 연결을 만들지 않는다. 데스크는 모의 매매다.
- 포지션을 열거나, 크기를 정하거나, 닫는 일을 사람이나 에이전트가 손으로 하지 않는다. 장부 규칙과 RISK만 한다.
- RISK의 결정을 뒤집지 않는다.
- 손익, 지연 시간, 커밋 해시를 지어내지 않는다. 모르면 "모름"이라고 쓴다.
- World Monitor 체크 3개가 모두 통과하기 전에는 READY라고 하지 않는다. 통과시키려고 `api.worldmonitor.app`으로 넘어가지 않는다.
- 비밀 값을 문서, 커밋, 로그, 채팅에 쓰지 않는다. 이름만 쓴다.

## 커밋
- 메시지는 **한글**, `분류: 내용` 형식. 분류별로 나눠서 커밋한다.
  - 예: `데스크: ...`, `장부: ...`, `테스트: ...`, `문서: ...`, `분석: ...`, `셀프호스트: ...`
- 커밋 전 확인:
  1. `git status`에 `.env*`, `*.db`, `state/`, `logs/`, `variant_cycles/`, `claude-cli-runs/`, `data/`가 없는지.
  2. `git diff --cached`에서 키처럼 보이는 문자열 검사 (예: `git diff --cached | grep -nE '(api[_-]?key|secret|token|password)\s*[=:]\s*\S{12,}|[A-Za-z0-9_-]{32,}'`).
- 주소(민트, 페어)는 공개 데이터라 테스트 픽스처에 써도 된다.

## 푸시
- `git fetch` 후 origin과 같은지 확인하고 `git push origin main`.
- 강제 푸시(`--force`), 이미 푸시한 커밋 고쳐 쓰기는 사용자 확인 없이 하지 않는다. 푸시가 거부되거나 인증이 실패하면 멈추고 보고한다.

## 코드
- 데스크는 Python 3 표준 라이브러리만 쓴다(설치 없음).
- 파라미터는 `config.py`(BASE)와 `manual/book_rules.py`(장부별)에만 둔다. 숫자를 코드 중간에 박지 않는다.
- 원 가이드 값과 데스크 가정을 구분한다. 가정에는 `ASSUMED`를 붙인다(예: `MEME_ASSUMED_P_WIN`). → [guide-params](../guide-params.md)
- 규칙을 바꾸면 `desk/README.md`, [paper-books.md](paper-books.md), 테스트를 같이 고친다.

## 보고
- 시간은 KST. 숫자는 장부 DB·로그·`git` 출력에서만.
- 모르는 것, 확인 못 한 것은 그렇게 적는다.
