# Factor Expansion Design

## 목적
현재 스크리너는 BB/RSI/SMA/weekly trend 기반으로 **과매도 + 저점 형성 + 초기 반전** 후보를 찾는 데는 충분히 작동합니다.

하지만 실제 운영 관점에서 false positive를 줄이고, 후보의 질을 높이려면 아래 3단계 보강이 필요합니다.

### Priority 1
1. earnings calendar data
2. relative strength vs QQQ

### Priority 2
3. ATR / volatility normalization

### Priority 3
4. candle structure / reversal bar quality

이 문서는 위 1차, 2차, 3차를 모두 포함한 확장 설계를 정리합니다.

---

## 현재 한계

### 1. Event risk blind spot
지금은 technical setup은 보지만, **earnings 직전/직후 이벤트 리스크**를 거의 반영하지 못합니다.

결과적으로 아래 같은 false positive가 생길 수 있습니다.
- earnings 이틀 전인데 oversold reversal처럼 보이는 종목
- earnings 직후 큰 gap 이후 기술적으로만 좋아 보이는 종목
- 실은 이벤트 베팅 성격이 강한데 turnaround candidate로 섞이는 경우

### 2. Real market context 부족
현재 `market_context_score` 는 이름과 달리 실질적으로는 **weekly_trend_penalty 기반 내부 점수**에 가깝습니다.

즉 아래는 아직 반영되지 않습니다.
- QQQ 대비 상대강도
- 시장이 약한 날에도 덜 무너진 종목
- 시장 반등 시 상대적으로 선행하는 종목

### 3. Volatility normalization 부족
현재는 `distance_to_20d_low`, `distance_to_60d_low` 같은 위치 기반 지표는 있지만,
종목별 변동성 차이를 직접 보정하는 축이 약합니다.

예를 들어:
- 변동성 높은 종목의 3% 반등
- 변동성 낮은 종목의 3% 반등

은 의미가 다르지만 현재 스코어링에서 충분히 구분되지 않습니다.

### 4. Reversal bar quality 부족
현재 reversal evidence는 주로 아래에 의존합니다.
- `sma_5`
- `close_improvement_streak`
- `rsi_3d_change`

하지만 실제 반전 quality에 중요한 아래 정보는 아직 없습니다.
- intraday rejection wick
- open 대비 close 회복
- gap down reclaim
- 종가가 당일 range 상단 쪽에서 마감했는지

---

## 설계 원칙

### 원칙 1. 현재 철학 유지
이 프로젝트는 **설명 가능한 turnaround screener** 입니다.
따라서 신규 지표도 black-box model이 아니라:
- 해석 가능
- reason/risk 문구와 연결 가능
- candidate snapshot에 남길 수 있음

형태여야 합니다.

### 원칙 2. 1차는 효과 큰 것부터
우선순위는 "있으면 좋은 것"이 아니라, **false positive를 크게 줄이는 것** 기준으로 둡니다.

### 원칙 3. persistence와 함께 설계
새 지표는 scoring에만 쓰고 끝내지 않고:
- `indicator_snapshot`
- Oracle `indicator_snapshot_json`
- 필요 시 문서/리포트

까지 함께 고려합니다.

### 원칙 4. hard filter는 보수적으로
신규 데이터가 불안정할 수 있으므로, 초기에는 hard reject보다:
- soft penalty
- explicit risk
- optional filter flag

를 우선 적용합니다.

---

# Phase 1, Priority 1

## 1-A. Earnings Calendar Data

### 목표
turnaround candidate 중 **실은 earnings event bet에 가까운 후보**를 걸러냅니다.

### 필요 필드
최소 필드:
- `next_earnings_date`
- `days_to_next_earnings`
- `days_since_last_earnings`

추가 가능 필드:
- `has_upcoming_earnings`
- `has_recent_earnings`
- `earnings_window_risk_level` (`low` / `medium` / `high`)

### 데이터 소스 후보
우선순위:
1. 기존 사용 provider에서 earnings date 제공 가능하면 reuse
2. 별도 lightweight earnings provider 추가
3. 수동 static cache file 또는 bootstrap file

### 설계 방향
초기 구현은 **최소 date 필드만** 사용합니다.
정교한 EPS surprise 같은 건 범위에서 제외합니다.

### scoring/filter 반영안
초기 추천:
- `days_to_next_earnings <= 2` → 강한 penalty 또는 optional hard filter
- `days_to_next_earnings <= 5` → moderate risk
- `days_since_last_earnings <= 2` → gap/volatility risk 추가

예시:
- `days_to_next_earnings <= 2` → `earnings_penalty = 8`
- `days_to_next_earnings <= 5` → `earnings_penalty = 4`
- `days_since_last_earnings <= 2` → `earnings_penalty = max(existing, 3)`

### reason / risk 문구 예시
risk:
- `실적 발표가 임박해 이벤트 리스크가 큼`
- `실적 발표 직후 변동성 구간일 수 있음`

reason은 보통 추가하지 않고 risk 중심으로 둡니다.

### snapshot 추가 필드
- `next_earnings_date`
- `days_to_next_earnings`
- `days_since_last_earnings`
- `earnings_penalty`

### failure policy
- earnings data가 없으면 전체 run 실패로 보지 않음
- snapshot에 `earnings_data_available=false` 또는 필드 생략
- metadata note에 source availability 기록 가능

---

## 1-B. Relative Strength vs QQQ

### 목표
시장 전체가 흔들리는 상황에서도:
- 덜 무너진 종목
- 먼저 회복하는 종목
- 시장보다 약한데 기술적으로만 oversold인 종목

을 구분합니다.

### 핵심 개념
단순 하락폭이 아니라 **benchmark 대비 상대 성과**를 봅니다.

### 필요 필드
최소 필드:
- `qqq_return_20d`
- `qqq_return_60d`
- `stock_return_20d`
- `stock_return_60d`
- `rel_strength_20d_vs_qqq`
- `rel_strength_60d_vs_qqq`

추가 가능 필드:
- `qqq_above_sma_20`
- `qqq_above_sma_60`
- `benchmark_regime`

### 계산 방식
추천 baseline:
- `stock_return_20d = (close / close_20d_ago - 1) * 100`
- `stock_return_60d = (close / close_60d_ago - 1) * 100`
- `rel_strength_20d_vs_qqq = stock_return_20d - qqq_return_20d`
- `rel_strength_60d_vs_qqq = stock_return_60d - qqq_return_60d`

### 구현 위치
옵션:
1. `pipeline` 에서 별도 benchmark history fetch 후 indicator merge
2. `indicator_engine` 에 benchmark context 주입

추천은 **pipeline에서 benchmark snapshot을 미리 계산하고 ticker indicator에 merge** 하는 방식입니다.

이유:
- QQQ는 ticker별 데이터가 아니라 run-level context
- 매 종목마다 중복 fetch를 막기 쉬움
- 향후 sector ETF benchmark 확장도 쉬움

### scoring 반영안
초기 추천:
- 기존 `market_context_score` 를 실제 relative strength 기반 보조 점수로 재정의 또는 확장
- weekly trend penalty는 separate component로 유지

예시:
- `rel_strength_20d_vs_qqq >= 5` → +5
- `rel_strength_20d_vs_qqq >= 2` → +3
- `rel_strength_20d_vs_qqq <= -5` → -5
- `rel_strength_60d_vs_qqq <= -8` → 추가 risk

### reason / risk 문구 예시
reason:
- `최근 20일 기준 QQQ 대비 상대적으로 덜 약함`
- `시장 대비 상대강도가 개선되는 구간`

risk:
- `최근 20일 기준 시장 대비 상대약세가 큼`
- `장세 반등 대비 추종력이 약할 수 있음`

### snapshot 추가 필드
- `qqq_return_20d`
- `qqq_return_60d`
- `stock_return_20d`
- `stock_return_60d`
- `rel_strength_20d_vs_qqq`
- `rel_strength_60d_vs_qqq`
- `relative_strength_score`

### failure policy
- QQQ history fetch 실패 시 전체 run 실패 대신 relative strength component만 비활성
- metadata에 benchmark fetch failure 기록

---

# Phase 2, Priority 2

## 2. ATR / Volatility Normalization

### 목표
"낮은 위치" 와 "비정상적으로 깨진 상태" 를 구분하고,
종목별 변동성 차이를 더 잘 반영합니다.

### 필요 필드
최소 필드:
- `atr_14`
- `atr_14_pct`
- `daily_range_pct`
- `bb_width_pct`

추가 가능 필드:
- `true_range_pct`
- `volatility_regime`
- `range_compression_5d`

### 계산 정의
추천 baseline:
- `true_range = max(high-low, abs(high-prev_close), abs(low-prev_close))`
- `atr_14 = mean(true_range over 14)`
- `atr_14_pct = atr_14 / close * 100`
- `daily_range_pct = (high - low) / close * 100`
- `bb_width_pct = (bb_upper - bb_lower) / close * 100`

### 활용 포인트
1. 변동성 과열 제외
2. stabilization 후보 가산
3. 동일한 distance-to-low라도 종목별 의미 차이 보정

### scoring/filter 반영안
초기 추천:
- `atr_14_pct` 가 너무 높으면 risk 또는 penalty
- `daily_range_pct` 가 과도하면 dead-cat bounce risk
- `bb_width_pct` 가 너무 넓으면 아직 불안정한 구조로 해석

예시:
- `atr_14_pct >= 6` → volatility penalty 4
- `daily_range_pct >= 7` → intraday instability risk
- `bb_width_pct` 가 최근 20일 평균보다 지나치게 넓으면 추가 penalty

### reason / risk 문구 예시
reason:
- `변동성 과열 없이 반등 시도가 나타남`

risk:
- `변동성이 아직 높아 바닥 확인이 이를 수 있음`
- `일중 range가 커서 신호 품질이 불안정함`

### snapshot 추가 필드
- `atr_14`
- `atr_14_pct`
- `daily_range_pct`
- `bb_width_pct`
- `volatility_penalty`

### 구현 메모
ATR은 technical indicator 성격이므로 `indicators/technicals.py` 에 두는 것이 자연스럽습니다.

---

# Phase 3, Priority 3

## 3. Candle Structure / Reversal Bar Quality

### 목표
그날의 반등이 **진짜 rejection인지**, 아니면 단순 noisy bounce인지 더 잘 구분합니다.

### 필요 필드
최소 필드:
- `close_above_open`
- `close_location_value`
- `lower_wick_ratio`
- `gap_down_pct`
- `gap_down_reclaim`

추가 가능 필드:
- `upper_wick_ratio`
- `real_body_pct`
- `inside_day`
- `bullish_engulfing_like`

### 계산 정의
추천 baseline:
- `close_above_open = close >= open`
- `close_location_value = (close - low) / (high - low)` if range > 0
- `lower_wick_ratio = (min(open, close) - low) / (high - low)` if range > 0
- `gap_down_pct = (today_open / prev_close - 1) * 100`
- `gap_down_reclaim = gap_down_pct < 0 and close >= prev_close`

### 해석
- 하단 wick이 길고 close가 range 상단이면 rejection signal 강화
- gap down 후 prev close를 회복하면 stronger reversal evidence
- upper wick이 너무 길면 chase 실패 risk 가능

### scoring 반영안
초기 추천:
- reversal bucket 안에 흡수
- 별도 큰 score bucket을 만들기보다 `reversal` 세부 점수 보강

예시:
- `close_location_value >= 0.7` → reversal +2
- `lower_wick_ratio >= 0.4` → reversal +2
- `gap_down_reclaim = true` → reversal +3

### reason / risk 문구 예시
reason:
- `하단 꼬리 이후 종가가 일중 상단에서 마감`
- `gap 하락 이후 회복 흐름이 확인됨`

risk:
- `종가가 일중 하단에 머물러 매수 우위 확인이 약함`

### snapshot 추가 필드
- `close_above_open`
- `close_location_value`
- `lower_wick_ratio`
- `gap_down_pct`
- `gap_down_reclaim`

### 구현 메모
이 필드들은 현재 OHLC 데이터만으로 계산 가능하므로 외부 데이터 의존성이 없습니다.
Priority 3이지만 구현 난이도 자체는 높지 않습니다.

---

# 아키텍처 영향

## 1. Data Layer

### earnings provider abstraction 추가
추천 인터페이스:
- `fetch_earnings_calendar(tickers, run_date) -> dict[ticker, earnings_info]`

형태 예시:
```python
{
  "AAPL": {
    "next_earnings_date": "2026-04-30",
    "days_to_next_earnings": 9,
    "days_since_last_earnings": 82,
  }
}
```

### benchmark history
QQQ는 ticker universe 외 별도 benchmark history로 fetch합니다.
가능하면 현재 market data provider abstraction을 reuse 합니다.

---

## 2. Pipeline Layer

추천 흐름:
1. universe load
2. ticker market history fetch 준비
3. QQQ benchmark history fetch
4. optional earnings calendar fetch
5. per-ticker indicator 계산
6. benchmark context merge
7. optional earnings context merge
8. scoring
9. snapshot/persistence

### 추가 helper 제안
- `build_benchmark_context(history_by_benchmark) -> dict[str, Any]`
- `merge_context_into_indicators(indicators, benchmark_context, earnings_info) -> dict[str, Any]`

---

## 3. Scoring Layer

### 현재 구조와의 연결
현재 `rank_candidates()` 는 snapshot row 하나를 받아:
- filter
- score
- reasons/risks 생성

을 수행합니다.

이 구조는 유지 가능합니다.
대신 snapshot 필드만 확장하면 됩니다.

### 추천 변경
- `market_context_score` 는 실제 상대강도 기반 점수로 재정의하거나,
  `weekly_trend_penalty` 와 분리해 더 명확히 계산
- earnings penalty, volatility penalty는 별도 helper로 분리
- candle structure는 reversal helper 안에 흡수

추천 helper 추가:
- `_score_relative_strength(...)`
- `_score_volatility(...)`
- `_apply_earnings_penalty(...)`
- `_candle_reversal_bonus(...)`

---

## 4. Snapshot / Persistence

### snapshot schema version
새 필드가 많이 늘어나므로 schema version 증가를 미리 설계해야 합니다.

추천:
- 현재: `schema_version = 1`
- 확장 후: `schema_version = 2`

### snapshot 확장 필드 묶음
Priority 1:
- earnings fields
- QQQ relative strength fields

Priority 2:
- ATR / volatility fields

Priority 3:
- candle structure fields

### Oracle 영향
추가 relational column은 당장 필요 없습니다.
기본 원칙은 유지:
- relational column은 핵심 조회 필드만
- 나머지는 `indicator_snapshot_json`

---

## 5. Reporting

### JSON report
현재처럼 자동 포함으로 충분합니다.
필요하면 별도 작업 없이 snapshot 확장 내용이 그대로 artifact에 남습니다.

### Markdown report
기본은 요약형 유지가 맞습니다.
다만 필요 시 후보별 한 줄 risk 강화 정도는 고려 가능합니다.
예:
- `earnings in 2d`
- `QQQ RS weak`
- `high volatility`

초기에는 Markdown 확장은 optional로 둡니다.

---

# 단계별 구현 순서

## Step 1, Priority 1-A earnings
1. earnings provider abstraction 추가
2. config/secrets/env wiring
3. pipeline merge
4. scoring penalty/risk 반영
5. snapshot 저장
6. 테스트

## Step 2, Priority 1-B relative strength
1. QQQ benchmark fetch 추가
2. benchmark return / relative strength 계산
3. scoring 반영
4. snapshot 저장
5. 테스트

## Step 3, Priority 2 ATR/volatility
1. ATR / range / BB width 계산 추가
2. scoring penalty/risk 반영
3. snapshot 저장
4. 테스트

## Step 4, Priority 3 candle structure
1. candle quality field 계산
2. reversal score 보강
3. snapshot 저장
4. 테스트

---

# 테스트 계획

## Unit tests
### earnings
- days-to-earnings 계산
- missing earnings data graceful fallback
- earnings penalty threshold 검증

### relative strength
- benchmark return 계산
- `rel_strength_20d_vs_qqq` 계산
- benchmark fetch 실패 fallback

### volatility
- ATR 계산 정확성
- `atr_14_pct`, `daily_range_pct`, `bb_width_pct` sanity check

### candle
- `close_location_value`, `lower_wick_ratio`, `gap_down_reclaim` 계산 검증

## Integration tests
- pipeline run 시 snapshot에 신규 필드 포함 확인
- Oracle persistence JSON 저장 확인
- JSON report 노출 확인

## Acceptance criteria
### Phase 1
- earnings risk와 QQQ relative strength가 후보 quality에 실제 영향을 준다
- snapshot과 Oracle JSON에 관련 필드가 저장된다
- missing external data로 run 전체가 깨지지 않는다

### Phase 2
- volatility 과열 종목이 명시적 risk/penalty를 받는다

### Phase 3
- reversal bar quality가 reason/risk에 더 직접적으로 반영된다

---

# 리스크와 대응

## 1. External data dependency 증가
특히 earnings data는 외부 의존성이 추가됩니다.

대응:
- optional provider
- fetch failure graceful degradation
- metadata note 남김

## 2. Score complexity 증가
신규 factor가 많아지면 score가 불투명해질 수 있습니다.

대응:
- bucket별 역할 유지
- reason/risk 문구 명확화
- snapshot 저장으로 traceability 확보

## 3. Overfitting 위험
factor를 많이 넣으면 과최적화 가능성이 있습니다.

대응:
- Priority 1 → 2 → 3 순차 적용
- 각 단계마다 false positive 변화 검토
- 한 번에 너무 많이 hard filter 하지 않음

---

# 권장 결론

## 결론 1
가장 먼저 보강할 것은:
- **earnings calendar data**
- **relative strength vs QQQ**

입니다.
이 둘이 실제 후보 quality를 가장 크게 바꿀 가능성이 높습니다.

## 결론 2
그 다음은 **ATR / volatility normalization** 입니다.
이 단계부터는 종목별 구조 차이를 더 잘 반영할 수 있습니다.

## 결론 3
마지막으로 **candle structure / reversal bar quality** 를 넣으면,
같은 oversold candidate 중 더 나은 반전 bar를 우선시할 수 있습니다.

---

# 추천 다음 액션
1. 이 문서를 기준으로 **Phase 1 구현 스펙 고정**
2. earnings data source 후보 결정
3. QQQ benchmark context 추가 설계
4. Phase 1부터 구현 시작
