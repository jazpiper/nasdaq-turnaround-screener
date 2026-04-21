# nasdaq-turnaround-screener

NASDAQ-100 종목을 매일 추적하면서, Bollinger Bands 하단 근처에 위치하고 최근 저점 형성 후 turnaround 가능성이 있는 후보를 추려내는 개인용 투자 리서치 스크리너입니다.

## Status
- Daily screener + staged intraday collector are runnable
- OpenClaw secret wiring strategy defined
- Oracle SQL write path is implemented for daily and intraday runs (opt-in)
- Candidate-level `indicator_snapshot_json` persistence is implemented in Oracle SQL
- Oracle Mongo API is not implemented yet and is currently out of scope

## Goals
- NASDAQ-100 전체를 매일 스캔
- BB 하단 근접/이탈 종목 필터링
- 최근 저점 형성 및 반등 가능성 시그널 점수화
- 상위 후보를 설명 가능한 형태로 요약
- OpenClaw가 cron으로 실행하고 결과를 읽어 daily briefing 생성
- 장중에는 Twelve Data staged collector를 보수적으로 6회만 실행해 EOD 스크리닝 입력을 보강

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
- `docs/storage.md`: Oracle SQL 중심 저장 전략과 future storage notes
- `docs/operations.md`: OpenClaw 연동 및 운영 runbook
- `docs/signals.md`: 현재 screening rules와 scoring 기준
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
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --persist-oracle-sql
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install --persist-oracle-sql
python scripts/run_daily.py --date 2026-04-21
python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday
python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday --persist-oracle-sql
pytest
```

현재 CLI는 daily screening과 staged intraday collection 둘 다 지원합니다.
일상 운영에서는 `python -m screener.cli.main collect-window ...` 또는 `scripts/run_intraday_window.py` 로 장중 수집 window 하나를 실행하고, `scripts/run_daily.py` 로 하루 마감 스크리닝을 수행합니다.
장중 runner는 collector command를 감싸는 얇은 wrapper이고, 일봉 runner는 `.venv`를 자동으로 준비한 뒤 결과를 `output/daily/YYYY-MM-DD/` 아래에 저장하고 `output/daily/latest` 포인터를 갱신합니다.

## Market Data Providers
- 기본적으로는 `yfinance` 를 사용합니다.
- `TWELVE_DATA_API_KEY` 가 있거나 OpenClaw local secrets 파일(`~/.openclaw/secrets.json`, override: `SCREENER_OPENCLAW_SECRETS_PATH`)에 `/twelveData/apiKey` 가 있으면 기본 provider가 자동으로 `twelve-data` 로 전환됩니다.
- `SCREENER_MARKET_DATA_PROVIDER=twelve-data` 또는 `yfinance` 로 명시하면 자동 선택보다 우선합니다.
- Twelve Data API key는 `TWELVE_DATA_API_KEY` 환경변수가 OpenClaw secrets보다 우선합니다.
- Twelve Data는 연결 자체는 되지만 free plan이 `8 credits/min` 이라, 전체 NASDAQ-100 daily screening의 기본 provider로 쓰기보다는 staged collection 용도로 다루는 편이 안전합니다.

## Intraday Operations Plan
- 기본 장중 수집 cadence는 `open-1`, `open-2`, `midday-1`, `midday-2`, `power-hour-1`, `power-hour-2` 의 6개 window입니다.
- 8회보다 6회를 기본값으로 둔 이유는 API quota, 재시도 여지, 장애 복구 단순성, 그리고 daily screener가 결국 종가 기준 판단을 한다는 점 때문입니다.
- `collect-window` 명령은 NASDAQ-100 정적 universe를 6개 window로 고정 분할하고, 각 window 내부에서는 ticker 요청을 분당 최대 8건 이하의 minute batch로 보수적으로 진행합니다.
- 결과는 `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../` 아래에 저장되며, metadata에는 성공/실패, minute batch, remaining ticker, 이번 window에서 미수집된 ticker가 함께 기록됩니다.
- 실무 흐름은 장중 collector가 staged snapshots를 쌓고, 장 마감 후 daily screener가 최종 후보/리포트를 생성하는 2단 구조입니다.
- `--use-staged-intraday` 또는 `SCREENER_DAILY_INTRADAY_SOURCE_MODE=prefer-staged` 를 사용하면 해당 날짜의 가장 최근 staged intraday quotes를 찾아 마지막 일봉 bar를 같은 날짜 snapshot으로 교체하거나, 새 날짜면 append 합니다. artifacts가 없으면 기존 provider history로 그대로 fallback 합니다.
- `--persist-oracle-sql` 또는 `SCREENER_ORACLE_SQL_ENABLED=1` 을 사용하면 성공한 daily/intraday 결과를 Oracle SQL에 저장합니다. credential은 `ORACLE_DB_USER`, `ORACLE_DB_PASSWORD`, `ORACLE_DB_CONNECT_STRING` 환경변수 또는 OpenClaw secrets(`/oracleDb/*`)에서 읽습니다.
- 예시:
  ```bash
  python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
  python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
  ```
- window 목록은 `SCREENER_INTRADAY_WINDOW_IDS`, output root는 `SCREENER_INTRADAY_OUTPUT_ROOT`, collector command는 `SCREENER_INTRADAY_COLLECTOR_COMMAND` 로 override 할 수 있습니다.

## Future Extensions
- MACD, gap, earnings proximity 같은 추가 factor 반영
- 섹터/시장 regime score 확장
- 백테스트와 score calibration
- rejected candidate audit / universe-level feature snapshots
- watchlist/history persistence
- 웹 대시보드 또는 subscriber report 서비스화
