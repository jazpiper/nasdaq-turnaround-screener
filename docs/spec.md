# Functional Spec

## 1. V1 Scope

### Inputs
- NASDAQ-100 ticker universe
- Daily OHLCV data
- Optional metadata
  - sector
  - earnings date
  - company name

### Processing Pipeline
1. Universe load
2. Price data refresh
3. Data normalization / validation
4. Indicator calculation
5. Candidate filtering
6. Candidate scoring
7. Ranking
8. Report generation
9. Optional persistence

## 2. Indicator Set
현재 구현된 핵심 지표:
- Bollinger Bands(20, 2)
- RSI(14)
- SMA 5 / 20 / 60
- distance from 20D low
- distance from 60D low
- 20D average volume 대비 volume ratio
- weekly trend context (`weekly_sma_5`, `weekly_sma_10`, `weekly_trend_penalty`, `weekly_trend_severe_damage`)
- earnings context (`next_earnings_date`, `days_to_next_earnings`, `days_since_last_earnings`, `earnings_penalty`)
- QQQ relative strength (`qqq_return_20d`, `qqq_return_60d`, `stock_return_20d`, `stock_return_60d`, `rel_strength_*`, `relative_strength_score`)
- volatility normalization (`atr_14`, `atr_14_pct`, `daily_range_pct`, `bb_width_pct`, `volatility_penalty`)
- candle structure / reversal quality (`close_above_open`, `close_location_value`, `lower_wick_ratio`, `upper_wick_ratio`, `real_body_pct`, `gap_down_pct`, `gap_down_reclaim`, `inside_day`, `bullish_engulfing_like`)

후속 후보:
- MACD histogram slope
- sector relative strength
- rejected candidate audit / universe-level feature snapshot

## 3. Core Filter Baseline
후보 선별 기본 조건:
- `close <= bb_lower * 1.02` 또는 `low <= bb_lower`
- 최근 20일 저점 근처
- 최소 데이터 길이 충족(예: 60 trading days 이상)
- 데이터 결손 / 비정상 값 없음
- 최소 유동성 기준 충족

## 4. Candidate Score Baseline
총 100점 예시:
- BB lower proximity: 25
- recent low / capitulation context: 20
- reversal evidence: 25
- volume behavior: 15
- market / sector context: 15

### Reversal Evidence Examples
- 5일선 회복 또는 회복 시도
- 최근 2~3일 종가 개선
- downside rejection wick
- gap down reclaim
- inside day bullish hold
- bullish engulfing-like pattern
- RSI 과매도 탈출 초기

## 5. Outputs

### 5.1 File Outputs
선택한 output directory 아래에 아래 파일을 생성합니다.
- `daily-report.md`
- `daily-report.json`
- `run-metadata.json`

일상 운영용 `scripts/run_daily.py` 는 기본적으로 `output/daily/YYYY-MM-DD/` 아래에 이 파일들을 생성합니다.

### 5.2 Candidate Fields
각 candidate는 최소한 아래 필드를 포함합니다.
- ticker
- score
- subscores
- close
- lower_bb
- rsi14
- distance_to_20d_low
- reasons[]
- risks[]
- generated_at

Optional persistence/debug fields:
- `indicator_snapshot` (rule 판단에 사용한 final feature snapshot)
- `snapshot_schema_version`

현재 JSON report는 `candidate.model_dump(mode="json")` 를 사용하므로, 이 optional field가 있으면 artifact에도 그대로 포함됩니다. Markdown report는 ticker / score / reasons / risks 중심 요약만 출력합니다.

### 5.3 JSON Example
```json
{
  "date": "2026-04-21",
  "universe": "NASDAQ-100",
  "run_mode": "daily",
  "candidate_count": 3,
  "candidates": [
    {
      "ticker": "AMD",
      "score": 78,
      "subscores": {
        "oversold": 21,
        "bottom_context": 16,
        "reversal": 22,
        "volume": 9,
        "market_context": 10
      },
      "reasons": [
        "BB 하단 터치 후 종가 기준 재진입",
        "최근 20일 저점 부근에서 하락폭 둔화",
        "5일선 회복 시도"
      ],
      "risks": [
        "중기 추세는 아직 하락"
      ]
    }
  ]
}
```

## 6. CLI Surface
```bash
python -m screener.cli.main run --date 2026-04-21
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
screener run --date 2026-04-21
```

현재 구현된 persistence flag는 Oracle SQL만 지원합니다. Mongo API persistence는 아직 구현되지 않았습니다.

## 7. Operational Requirements
- 장 종료 후 1회 daily run
- 실패 시 로그와 exit code 명확화
- OpenClaw에서 실행 가능한 단일 command 제공
- partial data issue는 metadata에 남기되 전체 run은 가능하면 지속
- dry-run 지원
- Oracle SQL persistence는 기본 비활성이며 `--persist-oracle-sql` 또는 `SCREENER_ORACLE_SQL_ENABLED=1` 일 때만 활성화

## 8. Non-goals
- 자동 주문 실행
- 포지션 sizing
- 실시간 intraday signal engine
- 투자 자문 책임 대체
