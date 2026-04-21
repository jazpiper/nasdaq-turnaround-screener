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

현재 구현 로직:
- severe damage 조건이면 후보에서 제외
- 약한 훼손이면 penalty만 부여
  - 대략 `3.0` 또는 `6.0` penalty
- `market_context_score = 10.0 - weekly_trend_penalty`

대표 risk:
- `주봉 추세가 아직 약해 강한 반전 확인이 더 필요함`
- `시장/섹터 맥락 확인이 필요함`

## 7. Extra Risk Note
추가로 아래 조건이면 risk를 더 붙입니다.
- `sma_20 < sma_60`

대표 risk:
- `중기 추세는 아직 하락 압력일 수 있음`

## 8. Ranking Philosophy
가장 많이 빠진 종목이 아니라, `과매도 + 저점 형성 + 전환 신호` 조합이 좋은 종목을 우선합니다.

## 9. Not Yet Implemented
아래는 여전히 검토 아이디어이지만, 현재 scoring/filter 코드에는 직접 들어가 있지 않습니다.
- earnings proximity penalty
- sector relative strength
- ATR 기반 변동성 필터
- long lower wick / candle pattern 정교화

## 10. Human Review Checklist
최종 후보 확인 시 아래를 같이 봅니다.
- 실적 발표 일정
- 섹터 뉴스
- 시장 전체 risk-on/off
- 장기 추세선 위치
