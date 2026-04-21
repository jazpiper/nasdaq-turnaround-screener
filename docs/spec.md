# Functional Spec

## V1 Scope

### Inputs
- NASDAQ-100 ticker universe
- Daily OHLCV data
- Optional metadata: sector, earnings date

### Processing
1. Universe load
2. Price data refresh
3. Indicator calculation
   - Bollinger Bands(20, 2)
   - 20D / 60D low distance
   - RSI(14)
   - short-term moving averages
   - volume ratio
4. Candidate filtering
5. Candidate scoring
6. Report generation

### Core Filter Draft
- close <= lower_bb * 1.02 또는 intraday lower_bb touch
- current close가 최근 20일 저점 근처
- 최근 급락 후 하락 속도 둔화 조건 일부 충족
- 유동성/데이터 품질 기준 충족

### Candidate Score Draft
총 100점 기준 예시:
- BB lower proximity: 25
- recent low / capitulation context: 20
- reversal evidence: 25
- volume behavior: 15
- market/sector context: 15

### Outputs
- `output/daily-report.md`
- `output/daily-report.json`
- candidate별:
  - ticker
  - total score
  - 주요 지표
  - 선정 이유 bullet
  - 리스크 note

### CLI
```bash
python -m screener run --date 2026-04-21
```

### Report Example
```json
{
  "date": "2026-04-21",
  "universe": "NASDAQ-100",
  "candidates": [
    {
      "ticker": "AMD",
      "score": 78,
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

## Operational Requirements
- 장 종료 후 1회 daily run
- 실패 시 로그와 exit code 명확화
- OpenClaw에서 실행 가능한 단일 command 제공
