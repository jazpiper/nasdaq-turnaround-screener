# Screening Signals

이 문서는 **현재 코드에 구현된 규칙만** 정리합니다. 아이디어 단계나 후속 확장 항목은 제외하고, 실제 후보 선별과 점수화에 쓰이는 기준만 남깁니다.

## 1. Hard Filters
후보로 들어오려면 아래를 모두 만족해야 합니다.

- 최소 히스토리: `bars_available >= 60`
- 유동성: `average_volume_20d >= 1_000_000`
- 바닥 근접 (아래 중 하나 이상):
  - Bollinger proximity: `close <= bb_lower * 1.04` 또는 `low <= bb_lower`
  - 최근 저점 근접: `distance_to_20d_low <= 8.0`
- 필수 값 존재:
  - `close`
  - `low`
  - `bb_lower`
  - `rsi_14`
  - `distance_to_20d_low`
  - `volume_ratio_20d`

## 2. Total Score Formula
최종 점수는 아래처럼 계산됩니다.

- `total_score = sum(subscores) - earnings_penalty - volatility_penalty - severe_weekly_penalty`
- 총점이 `0` 이면 후보 리스트에는 남기지 않고 제외합니다. 현재 최소 총점 cutoff는 `1` 입니다.
- earnings / volatility / severe_weekly 세 overlay는 서로 독립적으로 계산되고, 최종 점수에서 합산 차감됩니다.
- earnings overlay와 volatility overlay 각각의 내부에서는 여러 조건이 동시에 맞아도 penalty는 모두 더하지 않고 **가장 큰 값 하나만** 적용합니다.
- 총점과 각 subscore는 모두 정수(`int`)로 관리됩니다.
- threshold 상수는 `src/screener/scoring/thresholds.py` 에 모여 있습니다.

## 3. Oversold Context, max 25
주요 입력: `close`, `bb_lower`, `rsi_14`

해석:
- Bollinger lower band 근처일수록 점수 가산
- `RSI 14 <= 35` 일수록 점수 가산

대표 reason:
- `BB 하단 근처 또는 재진입 구간`
- `RSI 14가 과매도권 또는 초기 탈출 구간`

## 4. Local Bottom Context, max 20
주요 입력: `distance_to_20d_low`, `distance_to_60d_low`

해석:
- 20일 저점에 가까울수록 가산
- 60일 저점과도 멀지 않으면 추가 가산
- `최근 20일 저점 부근` reason은 `distance_to_20d_low <= 3.0` 일 때 붙습니다.
- `중기 저점권과도 멀지 않음` reason은 `distance_to_60d_low <= 8.0` 일 때 붙습니다.

대표 reason:
- `최근 20일 저점 부근`
- `중기 저점권과도 멀지 않음`

## 5. Reversal Evidence, max 25
주요 입력: `close`, `sma_5`, `close_improvement_streak`, `rsi_3d_change`

해석:
- 5일선 회복 여부
- 최근 종가 개선 streak
- RSI의 3일 변화량

대표 reason / risk:
- `5일선 회복 또는 회복 시도`
- `최근 2일 이상 종가 개선`
- `5일선 아래에 머물러 반전 확인이 약함`

## 6. Volume Behavior, max 15
주요 입력: `volume_ratio_20d`

해석:
- 너무 약한 거래량은 risk
- 평균 부근이면 과열되지 않은 반등 시도
- 크게 높으면 반등 시도에 거래량 유입으로 해석
- 현재 구현은 선형 점수 후 `0..15` 로 clip 하므로, `volume_ratio_20d >= 1.6` 부근부터는 추가 점수 차이가 더 커지지 않습니다.

대표 reason / risk:
- `거래량이 20일 평균 대비 과열되지 않음`
- `반등 시도에 거래량 유입이 동반됨`
- `거래량이 평균 대비 약해 신호 신뢰도가 낮을 수 있음`

## 7. Weekly Trend / Market Context, max 15
주요 입력:
- `weekly_close`, `weekly_sma_5`, `weekly_sma_10`
- `weekly_close_improving`, `weekly_trend_penalty`, `weekly_trend_severe_damage`
- `market_context_score`
- `qqq_return_20d`, `qqq_return_60d`
- `stock_return_20d`, `stock_return_60d`
- `rel_strength_20d_vs_qqq`, `rel_strength_60d_vs_qqq`
- `relative_strength_score`

현재 구현 로직:
- severe damage 조건이면 **필터 통과는 허용하되** `severe_weekly_penalty = 10` 을 차감하고 risk를 붙입니다.
  - severe damage는 `weekly_close < weekly_sma_10 * 0.85`, `weekly_sma_5 < weekly_sma_10`, `weekly_close_improving == false` 조합일 때 `true` 가 됩니다.
- 약한 훼손이면 `weekly_trend_penalty` 만 부여합니다.
  - `weekly_close < weekly_sma_10 * 0.9` 이고 `weekly_sma_5 < weekly_sma_10` 이며 개선 중이 아니면 penalty `6`
  - `weekly_close < weekly_sma_10 * 0.95` 이고 `weekly_sma_5 < weekly_sma_10` 이며 개선 중이 아니면 penalty `3`
- provider / indicator 단계가 먼저 `market_context_score = 10.0 - weekly_trend_penalty` baseline을 채웁니다.
- scoring 단계는 이 baseline에 QQQ 대비 상대강도 bonus / penalty를 추가로 반영합니다.
- `market_context_score` 가 snapshot에 없으면 scoring은 fallback `10.0` 을 사용해 중립으로 처리합니다.
- `rel_strength_60d_vs_qqq >= 4.0` 은 bonus를 더하지만, 현재 구현은 이 조건에 별도 reason 문구를 추가하지 않습니다.

대표 reason / risk:
- `최근 20일 기준 QQQ 대비 상대적으로 덜 약함`
- `시장 대비 상대강도가 개선되는 구간`
- `최근 20일 기준 시장 대비 상대약세가 큼`
- `장세 반등 대비 추종력이 약할 수 있음`
- `주봉 추세가 아직 약해 강한 반전 확인이 더 필요함`
- `주봉 추세가 심하게 훼손돼 반전 신뢰도가 낮음`
- `시장/섹터 맥락 확인이 필요함`

## 8. Earnings Risk Overlay
주요 입력:
- `earnings_data_available`
- `next_earnings_date`
- `days_to_next_earnings`
- `days_since_last_earnings`
- `earnings_penalty`

현재 구현 로직:
- earnings 데이터가 없으면 run은 계속 진행
- earnings 데이터가 없다고 자동 penalty를 주지는 않습니다. 대신 snapshot에 `earnings_data_available = false` 를 남깁니다.
- `days_to_next_earnings <= 2` 이면 penalty `8`
- `days_to_next_earnings <= 5` 이면 penalty `4`
- `days_since_last_earnings <= 2` 이면 penalty `3`
- 같은 earnings overlay 안에서는 여러 조건이 동시에 맞아도 가장 큰 penalty 하나만 차감합니다.
- earnings overlay penalty는 volatility overlay penalty와는 별도로 계산되고, 최종 점수에서는 두 overlay가 합산 차감됩니다.
- penalty는 총점에서 차감하고 risk를 함께 남깁니다.

대표 risk:
- `실적 발표가 임박해 이벤트 리스크가 큼`
- `실적 발표가 가까워 변동성 리스크가 있음`
- `실적 발표 직후 변동성 구간일 수 있음`

## 9. Volatility Normalization Overlay
주요 입력: `atr_14`, `atr_14_pct`, `daily_range_pct`, `bb_width_pct`, `volatility_penalty`

현재 구현 로직:
- `atr_14_pct >= 6.0` 이면 penalty `4`
- `daily_range_pct >= 7.0` 이면 penalty `2` 와 instability risk 추가
- `bb_width_pct >= 25.0` 이면 penalty `3` 과 구조 불안정 risk 추가
- 아래 3개가 모두 안정적이면 calm reason 추가
  - `atr_14_pct <= 3.5`
  - `daily_range_pct <= 4.5`
  - `bb_width_pct <= 18.0`
- 같은 volatility overlay 안에서는 여러 조건이 동시에 맞아도 가장 큰 penalty 하나만 차감합니다.

대표 reason / risk:
- `변동성 과열 없이 반등 시도가 나타남`
- `변동성이 아직 높아 바닥 확인이 이를 수 있음`
- `일중 range가 커서 신호 품질이 불안정함`
- `볼린저 밴드 폭이 넓어 아직 구조가 불안정함`

## 10. Candle Structure / Reversal Quality
주요 입력:
- `close_above_open`
- `close_location_value`
- `lower_wick_ratio`
- `upper_wick_ratio`
- `real_body_pct`
- `gap_down_pct`
- `gap_down_reclaim`
- `inside_day`
- `bullish_engulfing_like`

현재 구현 로직:
- candle structure는 `reversal` bucket 안에 흡수됩니다.
- `close_location_value >= 0.7` 이면 reversal 가산 + reason
- `lower_wick_ratio >= 0.4` 이면 reversal 가산
- `close_above_open = true` 이고 `real_body_pct >= 0.35` 이면 reversal 소폭 가산
- `gap_down_reclaim = true` 이면 reversal 가산 + reason
- `inside_day = true` 이고 양봉이면 reversal 소폭 가산
- `bullish_engulfing_like = true` 이면 reversal 가산 + reason
- `close_location_value <= 0.35` 이면 risk 추가
- `upper_wick_ratio >= 0.45` 이면 risk 추가

대표 reason / risk:
- `하단 꼬리 이후 종가가 일중 상단에서 마감`
- `실체가 커 매수 우위가 비교적 분명함`
- `inside day 안에서 매수 우위가 유지됨`
- `전일 몸통을 감싸는 bullish engulfing 유사 패턴`
- `gap 하락 이후 회복 흐름이 확인됨`
- `종가가 일중 하단에 머물러 매수 우위 확인이 약함`
- `상단 꼬리가 길어 추격 매수 실패 가능성이 남아 있음`

## 11. Extra Risk Note
추가로 아래 조건이면 risk를 더 붙입니다.
- `sma_20 < sma_60`

대표 risk:
- `중기 추세는 아직 하락 압력일 수 있음`

## 12. Ranking Philosophy
가장 많이 빠진 종목이 아니라, `과매도 + 저점 형성 + 전환 신호` 조합이 좋은 종목을 우선합니다.
- 총점이 `1` 미만인 후보는 노이즈를 줄이기 위해 정렬 대상에서 제외합니다.
- 동점이면 ticker 알파벳순으로 정렬합니다.

## 13. Candidate Snapshot Coverage
현재 candidate snapshot에는 아래 묶음이 저장됩니다.
- base technicals: `close`, `low`, `bb_lower`, `rsi_14`, `sma_5`, `sma_20`, `sma_60`
- bottom / volume context: `distance_to_20d_low`, `distance_to_60d_low`, `average_volume_20d`, `volume_ratio_20d`
- short-term reversal context: `close_improvement_streak`, `rsi_3d_change`
- weekly context: `weekly_*`, `market_context_score`
- benchmark context: `qqq_return_*`, `stock_return_*`, `rel_strength_*`
- scoring-derived field: `relative_strength_score`
  - 이 값은 upstream raw input이 아니라 scoring 단계가 `market_context` subscore를 기록하면서 채우는 값입니다.
- earnings overlay: `earnings_data_available`, `next_earnings_date`, `days_to_next_earnings`, `days_since_last_earnings`, `earnings_penalty`
- volatility overlay: `atr_14`, `atr_14_pct`, `daily_range_pct`, `bb_width_pct`, `volatility_penalty`
- severe weekly overlay: `weekly_trend_severe_damage`, `severe_weekly_penalty`
- candle structure: `close_above_open`, `close_location_value`, `lower_wick_ratio`, `upper_wick_ratio`, `real_body_pct`, `gap_down_pct`, `gap_down_reclaim`, `inside_day`, `bullish_engulfing_like`

## 14. Human Review Checklist
최종 후보 확인 시 아래를 같이 봅니다.
- 실적 발표 일정
- 섹터 뉴스
- 시장 전체 risk-on/off
- 장기 추세선 위치
