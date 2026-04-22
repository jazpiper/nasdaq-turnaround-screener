# nasdaq-turnaround-screener

NASDAQ-100 종목을 매일 스캔해 과매도 구간이면서 최근 저점 형성 뒤 초기 반전 신호가 겹치는 후보를 추리는 개인용 리서치 스크리너입니다. 자동 주문 시스템이 아니라, 설명 가능한 후보 발굴과 운영 가능한 batch workflow를 목표로 합니다.

## Current Scope
- NASDAQ-100 daily screener 실행과 markdown / JSON / metadata artifact 기록
- staged intraday collector 실행과 same-day quote를 daily run에 병합하는 보강 workflow
- weekly trend, earnings, QQQ 상대강도, volatility, candle structure 기반 설명 가능한 scoring
- Oracle SQL opt-in persistence와 explicit schema initialization 지원
- 날짜 구간 backtest skeleton으로 score / forward-return replay 지원

## Quick Start
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
python -m screener.cli.main run --date 2026-04-21 --dry-run
```

- `--date` 는 `America/New_York` 거래일 기준으로 넘기는 전제를 둡니다.

## Main Commands
### Daily
```bash
python -m screener.cli.main run --date 2026-04-21
python -m screener.cli.main run --date 2026-04-21 --use-staged-intraday
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql
python scripts/run_daily.py --date 2026-04-21 --skip-install
```

### Intraday
```bash
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --total-windows 1 --max-credits-per-minute 5
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --persist-oracle-sql
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
```

raw `collect-window` CLI 기본값은 `total_windows=6`, `max_credits_per_minute=8` 입니다. 운영 기본값은 wrapper(`scripts/run_intraday_window.py`) 쪽이며, 이 경로는 slot마다 full-universe 재수집을 하도록 `--total-windows 1 --max-credits-per-minute 5` 를 사용합니다.

### Oracle Setup
Oracle persistence를 쓸 때만 아래 1회성 초기화가 필요합니다.

```bash
python -m screener.cli.main init-oracle-schema
```

### Backtest
```bash
python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21
```

## Output Layout
- `output/daily/YYYY-MM-DD/`: `daily-report.md`, `daily-report.json`, `run-metadata.json`, `alert-events.json`
- `output/daily/latest/`: 가장 최근 daily run 포인터와 stable daily consumer path (`alert-events.json`)
- `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../`: staged intraday metadata, quote artifact, provisional `alert-events.json` (`run_intraday_window.py` 기본값은 full-universe 수집이므로 보통 `window-01-of-01`)
- `output/intraday/YYYY-MM-DD/latest-alert-events.json`: 같은 거래일의 최신 provisional intraday consumer entrypoint

artifact 필드와 운영 해석 기준은 `docs/architecture.md` 와 `docs/operations.md` 를 기준 문서로 봅니다.

## Project Layout
```text
src/screener/
  _pipeline/          internal daily pipeline modules (contracts, snapshot, core, providers, context)
  backtest.py         historical candidate replay / forward-return skeleton
  cli/                CLI entrypoint
  collector.py        staged intraday collection
  config.py           settings, environment variable resolution, OpenClaw secrets loader
  data/               market data fetch / normalize
  indicators/         technical indicator calculation
  intraday_artifacts.py  intraday artifact reader used by daily merge path
  intraday_ops.py     slot id normalization, collector command template assembly
  models/             Pydantic schemas for data structures
  pipeline.py         public daily pipeline facade
  reporting/          markdown / json report generation
  scoring/            candidate filter and ranking
  secrets.py          OpenClaw secrets file reader
  storage/            file and Oracle SQL persistence
  universe/           NASDAQ-100 universe loader
tests/               pytest suite
scripts/             cron-friendly daily / intraday runners
docs/                current-state documentation
```

## Documentation
- `docs/architecture.md`: 현재 구현된 시스템 구조, 데이터 흐름, 저장 방식
- `docs/signals.md`: 현재 코드 기준 필터, 점수화, penalty 규칙
- `docs/operations.md`: 실행 명령, OpenClaw 연동 방식, NY trading day 기준 운영 흐름
- `docs/openclaw-cron-runbook.md`: OpenClaw cron 등록과 consumer handoff용 운영 런북
- `docs/doc-review-2026-04-22.md`: 2026-04-22 문서 리뷰 반영 결과와 후속 개선 상태

## Intraday Scheduling Note
- `scripts/run_intraday_window.py` 는 slot 이름(`open-1` 등)을 스케줄 라벨로만 사용하고, 각 실행마다 NASDAQ-100 전체를 다시 수집합니다.
- 기본 wrapper command는 Twelve Data free plan 대비 버퍼를 더 두기 위해 `max_credits_per_minute=5` 를 사용합니다.
- Twelve Data가 일일 크레딧 소진 응답을 주면 해당 slot의 추가 ticker 호출을 즉시 중단하고, 남은 planned ticker는 `skipped_due_to_credit_exhaustion` 으로 metadata에 기록합니다.
- OpenClaw나 외부 오케스트레이터의 기본 daily consumer entrypoint는 `output/daily/latest/alert-events.json` 입니다.
