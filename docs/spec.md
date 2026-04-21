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
필수 지표:
- Bollinger Bands(20, 2)
- RSI(14)
- SMA 5 / 20 / 60
- distance from 20D low
- distance from 60D low
- 20D average volume 대비 volume ratio

후속 후보:
- ATR
- MACD histogram slope
- gap / wick pattern summary
- sector relative strength

## 3. Core Filter Draft
후보 선별 기본 조건:
- `close <= lower_bb * 1.02` 또는 intraday lower band touch
- 최근 20일 저점 근처
- 최소 데이터 길이 충족(예: 60 trading days 이상)
- 데이터 결손 / 비정상 값 없음
- 최소 유동성 기준 충족

## 4. Candidate Score Draft
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
- RSI 과매도 탈출 초기

## 5. Outputs

### 5.1 File Outputs
- `output/daily-report.md`
- `output/daily-report.json`
- `output/run-metadata.json`

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
python -m screener.cli run --date 2026-04-21
python -m screener.cli run --date 2026-04-21 --persist oracle-sql
python -m screener.cli run --date 2026-04-21 --persist oracle-mongo
```

## 7. Operational Requirements
- 장 종료 후 1회 daily run
- 실패 시 로그와 exit code 명확화
- OpenClaw에서 실행 가능한 단일 command 제공
- partial data issue는 metadata에 남기되 전체 run은 가능하면 지속
- dry-run 지원

## 8. Non-goals
- 자동 주문 실행
- 포지션 sizing
- 실시간 intraday signal engine
- 투자 자문 책임 대체
