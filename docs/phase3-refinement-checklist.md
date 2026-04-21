# Phase 3 Refinement Checklist

## 목표
기존 Phase 3 baseline 위에 candle quality refinement를 추가해 reversal signal의 품질을 더 잘 구분합니다.

범위:
1. upper wick / real body / inside day / engulfing-like field 추가
2. reversal scoring refinement
3. snapshot / docs / persistence sync

---

## Step 1, Candle Refinement Metrics
현재 상태: **done**

### Checklist
- [x] `upper_wick_ratio` 계산 추가
- [x] `real_body_pct` 계산 추가
- [x] `inside_day` 계산 추가
- [x] `bullish_engulfing_like` 계산 추가
- [x] snapshot 연결
- [x] technical tests 추가

---

## Step 2, Reversal Scoring Refinement
현재 상태: **done**

### Checklist
- [x] long upper wick risk 추가
- [x] real body strength reason/bonus 추가
- [x] inside day bullish hold bonus 추가
- [x] bullish engulfing-like bonus 추가
- [x] scoring tests 추가

### 현재 baseline
- `upper_wick_ratio >= 0.45` → risk
- `close_above_open = true` and `real_body_pct >= 0.35` → small reversal bonus
- `inside_day = true` and bullish close → small reversal bonus
- `bullish_engulfing_like = true` → reversal bonus + reason

---

## Step 3, Verification
현재 상태: **done**

### Checklist
- [x] `docs/signals.md` sync
- [x] `README.md` sync
- [x] Oracle SQL snapshot test sync
- [x] `pytest -q` 검증
- [x] manual daily run sanity check

---

## 완료 기준
- refinement field가 snapshot에 남는다
- reversal score가 candle quality를 더 정교하게 반영한다
- weak upper wick structure는 risk로 드러난다
- 관련 테스트가 모두 통과한다
