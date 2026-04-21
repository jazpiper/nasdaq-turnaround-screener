# Screening Signals

현재 구현은 아래 규칙을 기준으로 daily candidate를 고릅니다.
문서상 아이디어와 실코드가 섞이지 않도록, 이 문서는 **현재 구현 기준**을 우선 적습니다.

## 1. Hard Filters
후보로 들어오려면 아래를 모두 만족해야 합니다.

- 최소 히스토리: `bars_available >= 60`
- 유동성: `average_volume_20d >= 1_000_000`
- Bollinger proximity:
  - `close <= bb_lower * 1.02`
  - 또는 `low <= bb_lower`
- 최근 저점 근접: `distance_to_20d_low <= 5.0`
- 필수 snapshot 값 존재:
  - `close`
  - `low`
  - `bb_lower`
  - `rsi_14`
  - `distance_to_20d_low`
  - `volume_ratio_20d`
- severe weekly damage가 아니어야 함:
  - `weekly_trend_severe_damage == false`

## 2. Oversold Context, max 25
주요 입력:
- `close`
- `bb_lower`
- `rsi_14`

해석:
- Bollinger lower band 근처일수록 점수 가산
- `RSI 14 <= 35` 구간일수록 점수 가산

대표 reason:
- `BB 하단 근처 또는 재진입 구간`
- `RSI 14가 과매도권 또는 초기 탈출 구간`

## 3. Local Bottom Context, max 20
주요 입력:
- `distance_to_20d_low`
- `distance_to_60d_low`

해석:
- 20일 저점에 가까울수록 가산
- 60일 저점과도 멀지 않으면 추가 가산

대표 reason:
- `최근 20일 저점 부근`
- `중기 저점권과도 멀지 않음`

## 4. Reversal Evidence, max 25
주요 입력:
- `close`
- `sma_5`
- `close_improvement_streak`
- `rsi_3d_change`

해석:
- 5일선 회복 여부
- 최근 종가 개선 streak
- RSI의 3일 변화량

대표 reason / risk:
- `5일선 회복 또는 회복 시도`
- `최근 2일 이상 종가 개선`
- `5일선 아래에 머물러 반전 확인이 약함`

## 5. Volume Behavior, max 15
주요 입력:
- `volume_ratio_20d`

해석:
- 너무 약한 거래량은 risk
- 평균 부근이면 과열되지 않은 반등 시도
- 크게 높으면 반등 시도에 거래량 유입으로 해석

대표 reason / risk:
- `거래량이 20일 평균 대비 과열되지 않음`
- `반등 시도에 거래량 유입이 동반됨`
- `거래량이 평균 대비 약해 신호 신뢰도가 낮을 수 있음`

## 6. Weekly Trend / Market Context, max 15
주요 입력:
- `weekly_close`
- `weekly_sma_5`
- `weekly_sma_10`
- `weekly_close_improving`
- `weekly_trend_penalty`
- `weekly_trend_severe_damage`
- `market_context_score`
- `qqq_return_20d`
- `qqq_return_60d`
- `stock_return_20d`
- `stock_return_60d`
- `rel_strength_20d_vs_qqq`
- `rel_strength_60d_vs_qqq`
- `relative_strength_score`

현재 구현 로직:
- severe damage 조건이면 후보에서 제외
- 약한 훼손이면 penalty만 부여
  - 대략 `3.0` 또는 `6.0` penalty
- 기본값은 `market_context_score = 10.0 - weekly_trend_penalty`
- 여기에 QQQ 대비 상대강도를 추가로 반영
  - `rel_strength_20d_vs_qqq >= 5.0` 이면 가산
  - `rel_strength_20d_vs_qqq >= 2.0` 이면 소폭 가산
  - `rel_strength_20d_vs_qqq <= -5.0` 이면 감점 + risk
  - `rel_strength_60d_vs_qqq >= 4.0` 이면 추가 가산
  - `rel_strength_60d_vs_qqq <= -8.0` 이면 추가 감점 + risk

대표 reason / risk:
- `최근 20일 기준 QQQ 대비 상대적으로 덜 약함`
- `시장 대비 상대강도가 개선되는 구간`
- `최근 20일 기준 시장 대비 상대약세가 큼`
- `장세 반등 대비 추종력이 약할 수 있음`
- `주봉 추세가 아직 약해 강한 반전 확인이 더 필요함`
- `시장/섹터 맥락 확인이 필요함`

## 7. Earnings Risk Overlay
주요 입력:
- `earnings_data_available`
- `next_earnings_date`
- `days_to_next_earnings`
- `days_since_last_earnings`
- `earnings_penalty`

현재 구현 로직:
- earnings 데이터가 없으면 run은 계속 진행
- `days_to_next_earnings <= 2` 이면 penalty `8`
- `days_to_next_earnings <= 5` 이면 penalty `4`
- `days_since_last_earnings <= 2` 이면 penalty `3`
- penalty는 총점에서 차감하고 risk를 함께 남김

대표 risk:
- `실적 발표가 임박해 이벤트 리스크가 큼`
- `실적 발표가 가까워 변동성 리스크가 있음`
- `실적 발표 직후 변동성 구간일 수 있음`

## 8. Volatility Normalization Overlay
주요 입력:
- `atr_14`
- `atr_14_pct`
- `daily_range_pct`
- `bb_width_pct`
- `volatility_penalty`

현재 구현 로직:
- `atr_14_pct >= 6.0` 이면 penalty `4`
- `daily_range_pct >= 7.0` 이면 instability risk 추가
- `bb_width_pct >= 25.0` 이면 구조 불안정 risk 추가
- penalty는 총점에서 차감하고 snapshot에 `volatility_penalty` 로 남김
- 반대로 아래 3개가 모두 안정적이면 reason을 추가
  - `atr_14_pct <= 3.5`
  - `daily_range_pct <= 4.5`
  - `bb_width_pct <= 18.0`

대표 reason / risk:
- `변동성 과열 없이 반등 시도가 나타남`
- `변동성이 아직 높아 바닥 확인이 이를 수 있음`
- `일중 range가 커서 신호 품질이 불안정함`
- `볼린저 밴드 폭이 넓어 아직 구조가 불안정함`

## 9. Candle Structure / Reversal Bar Quality
주요 입력:
- `close_above_open`
- `close_location_value`
- `lower_wick_ratio`
- `gap_down_pct`
- `gap_down_reclaim`

현재 구현 로직:
- candle structure는 `reversal` bucket 안에 흡수합니다
- `close_location_value >= 0.7` 이면 reversal 가산 + reason 추가
- `lower_wick_ratio >= 0.4` 이면 reversal 가산
- `gap_down_reclaim = true` 이면 reversal 가산 + reason 추가
- `close_location_value <= 0.35` 이면 risk 추가

대표 reason / risk:
- `하단 꼬리 이후 종가가 일중 상단에서 마감`
- `gap 하락 이후 회복 흐름이 확인됨`
- `종가가 일중 하단에 머물러 매수 우위 확인이 약함`

## 10. Extra Risk Note
추가로 아래 조건이면 risk를 더 붙입니다.
- `sma_20 < sma_60`

대표 risk:
- `중기 추세는 아직 하락 압력일 수 있음`

## 11. Ranking Philosophy
가장 많이 빠진 종목이 아니라, `과매도 + 저점 형성 + 전환 신호` 조합이 좋은 종목을 우선합니다.

## 12. Not Yet Implemented
아래는 여전히 검토 아이디어이지만, 현재 scoring/filter 코드에는 직접 들어가 있지 않습니다.
- sector relative strength
- candle structure refinement (upper wick / engulfing / inside day)
- earnings API direct integration

## 13. Human Review Checklist
최종 후보 확인 시 아래를 같이 봅니다.
- 실적 발표 일정
- 섹터 뉴스
- 시장 전체 risk-on/off
- 장기 추세선 위치
