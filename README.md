# nasdaq-turnaround-screener

NASDAQ-100 종목을 매일 추적하면서, Bollinger Bands 하단 근처에 위치하고 최근 저점 형성 후 turnaround 가능성이 있는 후보를 추려내는 개인용 투자 리서치 스크리너입니다.

## Status
- Phase 0, architecture and documentation bootstrapped
- Core Python scaffold and CLI placeholder pipeline added
- OpenClaw secret wiring strategy defined
- Oracle SQL / Oracle Mongo API access paths confirmed separately

## Goals
- NASDAQ-100 전체를 매일 스캔
- BB 하단 근접/이탈 종목 필터링
- 최근 저점 형성 및 반등 가능성 시그널 점수화
- 상위 후보를 설명 가능한 형태로 요약
- OpenClaw가 cron으로 실행하고 결과를 읽어 daily briefing 생성

## Principles
- 이 프로젝트는 매수/매도 자동화가 아니라 후보 발굴용 research assistant입니다.
- 추천보다 설명 가능한 filtering과 ranking을 우선합니다.
- OpenClaw core를 수정하지 않고 외부 프로젝트로 독립 유지합니다.
- 신호 계산은 deterministic하게 유지하고, 데이터 소스/저장소는 교체 가능하게 설계합니다.

## Proposed Layout
```text
nasdaq-turnaround-screener/
  README.md
  docs/
  src/
    screener/
      universe/
      data/
      indicators/
      scoring/
      reporting/
      storage/
      cli/
  tests/
  output/
```

## Documents
- `docs/product.md`: 제품 개요와 사용자 가치
- `docs/spec.md`: 기능 요구사항과 출력 포맷
- `docs/architecture.md`: 시스템 구조와 데이터 흐름
- `docs/storage.md`: Oracle SQL / Mongo 저장 전략
- `docs/operations.md`: OpenClaw 연동 및 운영 runbook
- `docs/signals.md`: screening rules 초안
- `docs/roadmap.md`: 단계별 구현 계획

## Initial Scope
1. NASDAQ-100 universe 수집
2. 일봉 기반 technical indicators 계산
3. BB 하단 + 최근 저점 + 반등 가능성 score 산출
4. daily markdown/json report 생성
5. OpenClaw 연동용 CLI entrypoint 제공

## Current Scaffold
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m screener.cli.main run --date 2026-04-21 --dry-run
python -m screener.cli.main run --date 2026-04-21
python scripts/run_daily.py --date 2026-04-21
pytest
```

현재 CLI는 placeholder pipeline을 실행하고, dry-run이 아니면 `output/` 아래에 markdown/json metadata artifact를 생성합니다.
일상 운영에서는 `scripts/run_daily.py` 를 사용하면 `.venv`를 자동으로 준비하고, 결과를 `output/daily/YYYY-MM-DD/` 아래에 저장한 뒤 `output/daily/latest` 포인터를 갱신합니다.
구체적인 universe, market data, indicator, scoring 구현은 분리된 interface를 통해 이후 병합하도록 남겨두었습니다.

## Market Data Providers
- 기본적으로는 `yfinance` 를 사용합니다.
- `TWELVE_DATA_API_KEY` 가 있거나 OpenClaw local secrets 파일(`~/.openclaw/secrets.json`, override: `SCREENER_OPENCLAW_SECRETS_PATH`)에 `/twelveData/apiKey` 가 있으면 기본 provider가 자동으로 `twelve-data` 로 전환됩니다.
- `SCREENER_MARKET_DATA_PROVIDER=twelve-data` 또는 `yfinance` 로 명시하면 자동 선택보다 우선합니다.
- Twelve Data API key는 `TWELVE_DATA_API_KEY` 환경변수가 OpenClaw secrets보다 우선합니다.

## Future Extensions
- RSI, MACD, volume, gap, earnings proximity 반영
- 섹터/시장 regime score 추가
- 백테스트와 score calibration
- watchlist/history persistence
- 웹 대시보드 또는 subscriber report 서비스화
