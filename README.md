# nasdaq-turnaround-screener

NASDAQ-100 종목을 매일 스캔해 과매도 구간이면서 최근 저점 형성 뒤 초기 반전 신호가 겹치는 후보를 추리는 개인용 리서치 스크리너입니다. 자동 주문 시스템이 아니라, 설명 가능한 후보 발굴과 운영 가능한 batch workflow를 목표로 합니다.

## Current Scope
- daily screener 실행 가능
- staged intraday collector 실행 가능
- same-day intraday snapshot을 daily run에 병합 가능
- Oracle SQL opt-in persistence 구현 완료
- Oracle SQL schema explicit init command 추가
- candidate-level `indicator_snapshot` / `indicator_snapshot_json` 저장 구현 완료
- 날짜 구간 backtest skeleton 실행 가능
- 현재 구현된 factor:
  - weekly trend context
  - earnings context
  - relative strength vs QQQ
  - volatility normalization
  - candle structure / reversal quality

## Quick Start
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
python -m screener.cli.main run --date 2026-04-21 --dry-run
```

## Main Commands
```bash
python -m screener.cli.main run --date 2026-04-21
python -m screener.cli.main run --date 2026-04-21 --use-staged-intraday
python -m screener.cli.main init-oracle-schema
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql
python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21

python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0 --total-windows 1 --max-credits-per-minute 7
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install
python scripts/run_daily.py --date 2026-04-21 --skip-install
```

## Output Layout
- `output/daily/YYYY-MM-DD/`: `daily-report.md`, `daily-report.json`, `run-metadata.json`
- `output/daily/latest/`: 가장 최근 daily run 포인터
- `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-.../`: staged intraday metadata와 quote artifact (`run_intraday_window.py` 기본값은 full-universe 수집이므로 보통 `window-01-of-01`)

## Project Layout
```text
src/screener/
  _pipeline/       internal daily pipeline modules
  backtest.py      historical candidate replay / forward-return skeleton
  cli/            CLI entrypoint
  collector.py    staged intraday collection
  data/           market data fetch / normalize
  indicators/     technical indicator calculation
  pipeline.py     public daily pipeline facade
  reporting/      markdown / json report generation
  scoring/        candidate filter and ranking
  storage/        file and Oracle SQL persistence
  universe/       NASDAQ-100 universe loader
tests/            pytest suite
scripts/          cron-friendly daily / intraday runners
docs/             current-state documentation
```

## Documentation
- `docs/architecture.md`: 현재 구현된 시스템 구조, 데이터 흐름, 저장 방식
- `docs/signals.md`: 현재 코드 기준 필터, 점수화, penalty 규칙
- `docs/operations.md`: 실행 명령, OpenClaw 연동 방식, NY trading day 기준 운영 흐름

## Intraday Scheduling Note
- `scripts/run_intraday_window.py` 는 slot 이름(`open-1` 등)을 스케줄 라벨로만 사용하고, 각 실행마다 NASDAQ-100 전체를 다시 수집합니다.
- 기본 wrapper command는 Twelve Data free plan 대비 버퍼를 두기 위해 `max_credits_per_minute=7` 을 사용합니다.
