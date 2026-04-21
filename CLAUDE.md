# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'

# Run daily screener
python -m screener.cli.main run --date 2026-04-21
python -m screener.cli.main run --date 2026-04-21 --dry-run
python -m screener.cli.main run --date 2026-04-21 --use-staged-intraday
python -m screener.cli.main run --date 2026-04-21 --persist-oracle-sql

# Run intraday window collection (Twelve Data)
python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0
python scripts/run_intraday_window.py --date 2026-04-21 --window-id open-1 --skip-install

# Run scripts (wrap the CLI with .venv activation + output/daily/latest symlink)
python scripts/run_daily.py --date 2026-04-21
python scripts/run_daily.py --date 2026-04-21 --use-staged-intraday --persist-oracle-sql

# Tests
pytest
pytest tests/test_scoring.py          # single test file
pytest tests/test_pipeline.py -k test_run_returns_candidates  # single test
```

## Architecture

The screener is a **two-stage pipeline**: staged intraday collection during market hours, then a daily scoring run after close.

### Core data flow

```
universe loader → market data fetcher → indicator engine → candidate filter → scoring engine → report builder → (optional) Oracle SQL
```

All of this runs through `ScreenPipeline` in `src/screener/pipeline.py`. The pipeline accepts injectable Protocol interfaces for every stage, making unit testing straightforward.

### Key modules

| Module | Role |
|---|---|
| `pipeline.py` | Orchestrates the full screening run; owns `ScreenPipeline` and the injectable provider Protocols |
| `scoring/ranking.py` | Hard filter (`filter_candidates`) → score each subscore bucket → `rank_candidates` |
| `indicators/technicals.py` | Computes all OHLCV-derived columns including BB, RSI, ATR, candle structure, weekly context |
| `collector.py` | `TwelveDataWindowCollector` — splits NASDAQ-100 into N windows, fetches one window per call |
| `intraday_artifacts.py` / `intraday_ops.py` | Discovers the latest staged snapshot for the day and merges it into the daily history before scoring |
| `config.py` | `Settings` dataclass + `get_settings()` — reads env vars and OpenClaw secrets |
| `secrets.py` | Loads `~/.openclaw/secrets.json` (or `SCREENER_OPENCLAW_SECRETS_PATH`) for credentials |
| `storage/oracle_sql.py` | Opt-in Oracle persistence for both daily runs and intraday collections |
| `models/schemas.py` | Pydantic models: `CandidateResult`, `ScreenRunResult`, `PipelineContext`, etc. |

### Scoring (max 100 before penalties)

Five subscore buckets in `scoring/ranking.py`:
- **oversold** (max 25): BB proximity + RSI ≤ 35
- **bottom_context** (max 20): distance to 20d/60d low
- **reversal** (max 25): SMA-5 recovery + close streak + RSI slope + candle structure bonuses
- **volume** (max 15): volume_ratio_20d vs 20d average
- **market_context** (max 15): weekly trend penalty + QQQ relative strength

Penalties subtracted from total: `earnings_penalty` (up to 8) + `volatility_penalty` (up to 4+). Candidates with `weekly_trend_severe_damage=True` are filtered before scoring.

### Hard filter thresholds (in `filter_candidates`)

`bars_available >= 60`, `average_volume_20d >= 1_000_000`, `close <= bb_lower * 1.02` or `low <= bb_lower`, `distance_to_20d_low <= 5.0`, `weekly_trend_severe_damage == False`.

### Output artifacts

Daily run writes to `output/daily/YYYY-MM-DD/`:
- `daily-report.json` — full candidate list with `indicator_snapshot` (`schema_version=2`)
- `daily-report.md` — human-readable summary
- `run-metadata.json` — failures, notes, run config

Intraday runs write to `output/intraday/YYYY-MM-DD/window-XX-of-YY/run-<timestamp>/`.

### Market data providers

Default is `yfinance`. Set `SCREENER_MARKET_DATA_PROVIDER=twelve-data` or pass `--market-data-provider` to switch. Twelve Data uses `TWELVE_DATA_API_KEY` env var (takes priority) or the OpenClaw secrets key `/twelveData/apiKey`. The free plan is limited to 8 credits/min, so Twelve Data is reserved for staged intraday collection, not daily batch.

### Oracle SQL persistence

Opt-in via `--persist-oracle-sql` or `SCREENER_ORACLE_SQL_ENABLED=1`. Credentials from env vars (`ORACLE_DB_USER`, `ORACLE_DB_PASSWORD`, `ORACLE_DB_CONNECT_STRING`) or OpenClaw secrets (`/oracleDb/*`). Returns a run_id echoed to stdout.

### Intraday staged mode

`--use-staged-intraday` (or `SCREENER_DAILY_INTRADAY_SOURCE_MODE=prefer-staged`) makes the daily run find the most recent `collected-quotes.json` for the date and replace/append the last bar of each ticker's history before scoring. Falls back silently to raw provider data if no artifacts exist.

### OpenClaw integration

OpenClaw runs the CLI via cron, reads the output artifacts, and generates a daily briefing. The screener does not modify OpenClaw core. Secrets are accessed via `~/.openclaw/secrets.json`.
