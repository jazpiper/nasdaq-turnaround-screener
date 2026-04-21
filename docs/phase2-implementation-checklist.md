# Phase 2 Implementation Checklist

## 목표
`docs/factor-expansion-design.md` 기준으로 **Priority 2** 인 ATR / volatility normalization baseline 을 실제 코드에 반영합니다.

범위:
1. ATR / volatility indicator 계산
2. volatility penalty / risk overlay
3. snapshot / report / persistence sync

---

## 구현 원칙
- 기존 Phase 1 scoring 흐름을 유지하면서 additive overlay 로 넣는다.
- 데이터가 부족하면 penalty를 강제하지 않고 graceful fallback 한다.
- 신규 필드는 `indicator_snapshot_json` 까지 함께 연결한다.
- 테스트 추가 후 `pytest -q` 로 검증한다.

---

## Step 1, Technical Volatility Metrics
현재 상태: **done**

### Checklist
- [x] `atr_14` 계산 추가
- [x] `atr_14_pct` 계산 추가
- [x] `daily_range_pct` 계산 추가
- [x] `bb_width_pct` 계산 추가
- [x] indicator engine latest snapshot 연결
- [x] technical indicator tests 추가

---

## Step 2, Volatility Overlay Scoring
현재 상태: **done**

### Checklist
- [x] `volatility_penalty` 계산 추가
- [x] high volatility risk 문구 추가
- [x] calm volatility reason 문구 추가
- [x] total score 에 penalty 반영
- [x] snapshot 필드 추가

### 현재 threshold
- `atr_14_pct >= 6.0` → penalty `4`
- `daily_range_pct >= 7.0` → instability risk
- `bb_width_pct >= 25.0` → structure instability risk
- 아래 3개가 모두 안정적이면 calm reason 추가
  - `atr_14_pct <= 3.5`
  - `daily_range_pct <= 4.5`
  - `bb_width_pct <= 18.0`

---

## Step 3, Docs / Persistence / Verification
현재 상태: **done**

### Checklist
- [x] `docs/signals.md` sync
- [x] `README.md` status sync
- [x] Oracle SQL snapshot test sync
- [x] pipeline snapshot test sync
- [x] `pytest -q` 검증

---

## 완료 기준
- volatility 지표가 snapshot 에 남는다
- scoring 이 volatility penalty 를 총점에 반영한다
- 데이터 부족 시 run 전체는 계속된다
- 관련 테스트가 모두 통과한다
