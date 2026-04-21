# Phase 3 Implementation Checklist

## 목표
`docs/factor-expansion-design.md` 기준으로 **Priority 3** 인 candle structure / reversal bar quality baseline 을 실제 코드에 반영합니다.

범위:
1. candle structure indicator 계산
2. reversal score 보강
3. snapshot / persistence / docs sync

---

## 구현 원칙
- 기존 reversal bucket 을 유지하고, candle quality는 그 안에서 additive bonus/risk 로 반영한다.
- 외부 데이터 의존성 없이 현재 OHLC 데이터만 사용한다.
- 신규 필드는 `indicator_snapshot_json` 까지 함께 연결한다.
- 테스트 추가 후 `pytest -q` 로 검증한다.

---

## Step 1, Candle Structure Metrics
현재 상태: **done**

### Checklist
- [x] `close_above_open` 계산 추가
- [x] `close_location_value` 계산 추가
- [x] `lower_wick_ratio` 계산 추가
- [x] `gap_down_pct` 계산 추가
- [x] `gap_down_reclaim` 계산 추가
- [x] indicator engine latest snapshot 연결
- [x] technical indicator tests 추가

---

## Step 2, Reversal Quality Scoring
현재 상태: **done**

### Checklist
- [x] reversal bucket 안에 candle bonus 반영
- [x] strong close reason 문구 추가
- [x] gap reclaim reason 문구 추가
- [x] weak close risk 문구 추가
- [x] scoring tests 추가

### 현재 baseline
- `close_location_value >= 0.7` → reversal 가산 + reason
- `lower_wick_ratio >= 0.4` → reversal 가산
- `gap_down_reclaim = true` → reversal 가산 + reason
- `close_location_value <= 0.35` → risk 추가

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
- candle structure 지표가 snapshot 에 남는다
- reversal score 가 candle quality 를 반영한다
- 약한 종가 위치는 risk 로 드러난다
- 관련 테스트가 모두 통과한다
