# Phase 1 Implementation Checklist

## 목표
`docs/factor-expansion-design.md` 기준으로 **Priority 1** 을 실제 코드에 반영합니다.

범위:
1. earnings calendar data
2. relative strength vs QQQ

이 문서는 구현 순서를 고정하고, 각 step 진행 상태를 체크하기 위한 작업용 체크리스트입니다.

---

## 구현 원칙
- 먼저 **효과가 크고 외부 의존성이 적은 최소 구현**부터 넣는다.
- 외부 데이터 실패로 daily run 전체가 깨지지 않게 한다.
- 신규 필드는 `indicator_snapshot_json` 까지 함께 연결한다.
- 각 step 마다 테스트를 추가하고 `pytest -q` 로 검증한다.

---

## Step 1, Earnings Context Baseline
현재 상태: **done**

### Checklist
- [x] earnings provider abstraction 추가
- [x] file-backed earnings source 지원
- [x] config/env wiring 추가
- [x] pipeline 에서 ticker별 earnings context merge
- [x] scoring 에 earnings penalty / risk 반영
- [x] snapshot 필드 추가
- [x] unit/integration tests 추가
- [x] `pytest -q` 통과

### 이번 step의 구현 범위
초기 버전은 외부 API 확정 전에도 동작하도록 아래 형태로 갑니다.
- `SCREENER_EARNINGS_CALENDAR_PATH` 또는 설정 path 기반 JSON file source
- 필드:
  - `next_earnings_date`
  - `days_to_next_earnings`
  - `days_since_last_earnings`
  - `earnings_penalty`
- 데이터가 없으면 graceful fallback

### 보류
- 외부 earnings API 직접 연동
- EPS surprise / estimate / guidance 반영

---

## Step 2, QQQ Relative Strength Baseline
현재 상태: **done**

### Checklist
- [x] QQQ benchmark history fetch 추가
- [x] 20d / 60d benchmark return 계산
- [x] stock vs QQQ relative strength 계산
- [x] scoring 반영
- [x] snapshot 필드 추가
- [x] failure fallback 처리
- [x] tests 추가
- [x] `pytest -q` 통과

### 목표 필드
- `qqq_return_20d`
- `qqq_return_60d`
- `stock_return_20d`
- `stock_return_60d`
- `rel_strength_20d_vs_qqq`
- `rel_strength_60d_vs_qqq`
- `relative_strength_score`

---

## Step 3, Priority 1 Hardening
현재 상태: **in progress**

### Checklist
- [x] metadata note / failure message 정리
- [x] JSON artifact 확인
- [x] Oracle snapshot 저장 확인
- [x] 문서 sync
- [x] 수동 daily run sanity check

### Hardening note
- 수동 run 자체는 성공했지만, 초기 확인 시 현재 환경에서는 기본 provider가 `twelve-data` 로 자동 선택되면서 free plan `8 credits/min` 제한에 걸려 candidate가 0건으로 끝났습니다.
- 구현 관점에서는 fallback note가 정상 기록되는 것을 확인했고, 기능 검증 자체는 테스트로 보강했습니다.
- 이후 hardening으로 daily 기본 provider 자동 선택은 다시 `yfinance` 로 고정했고, Twelve Data는 명시 선택 또는 staged collector 위주로 쓰도록 정리했습니다.

---

## 실행 순서
1. Step 1 구현
2. 테스트
3. Step 2 구현
4. 테스트
5. Step 3 hardening
6. 문서/검증

---

## 완료 기준
- earnings와 relative strength가 실제 candidate quality에 영향을 준다
- 데이터가 없거나 fetch 실패여도 run 전체는 계속된다
- JSON report / Oracle snapshot 에 신규 필드가 남는다
- 관련 테스트가 모두 통과한다
