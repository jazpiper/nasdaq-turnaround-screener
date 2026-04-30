# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build, Test, and Development Commands

- `uv sync --extra dev` — create/update `.venv` from `uv.lock` with dev dependencies.
- `uv run pytest` — full test suite; `uv run pytest tests/test_cli.py -q` for targeted iteration.
- `uv run python -m screener.cli.main run --date 2026-04-21 --dry-run` — daily screener, no artifact writes.
- `uv run python scripts/run_daily.py --date 2026-04-21 --skip-install` — cron wrapper; manages `output/daily/latest` symlink.
- `uv run python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0` — intraday collection window.
- `uv run python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21` — replay historical scoring; writes forward-return artifacts.
- `uv run python -m screener.cli.main init-oracle-schema` — one-time Oracle table setup.

## Architecture: Data Flow

The pipeline is a **provider-based, daily-batch screener** for NASDAQ-100 turnaround candidates. The public facade is `pipeline.py`; internal steps live in `_pipeline/`.

```
CLI run
  → UniverseProvider.load_universe()          # NASDAQ-100 tickers from CSV
  → MarketDataProvider.prepare()              # batch-fetch OHLCV via yfinance (or Twelve Data)
  → IndicatorEngine.compute(history)          # 40+ technical metrics per ticker
  → merge_benchmark_context()                 # inject QQQ 20d/60d returns, relative strength
  → merge_earnings_context()                  # inject days-to/since-earnings, imminent penalty
  → CandidateScorer.evaluate()                # score, tier, reasons, risks
  → write artifacts + optional Oracle persist
```

**Intraday enrichment** is opt-in: `collect-window` stores minute-level quotes under `output/intraday/`. When `daily_intraday_source_mode=prefer-staged`, `PreferredIntradaySnapshotMarketDataProvider` wraps the base provider and merges the staged quote into the daily bar. Daily OHLCV remains the source of truth; intraday is enrichment only.

## Architecture: Scoring System

Scoring lives in `scoring/ranking.py` with threshold constants in `scoring/thresholds.py` and tier logic in `scoring/tiering.py`.

**Hard filters** (block a ticker entirely):
- Minimum 60 bars of history
- Average volume ≥ 1M
- Must be near lower Bollinger band (≤1.04×) **or** within 5% of recent low

**Four subscores** (0–25 each):
- `_score_oversold`: BB proximity (60%) + RSI14 (40%); bonuses for strong candle patterns
- `_score_bottom_context`: distance to 20d low (60%) + 60d low (40%)
- `_score_reversal`: close improvement streak + above SMA-5 + RSI 3d delta; candle pattern bonuses/penalties
- `_score_volume`: 20d-vs-5d average volume ratio

**Risk adjustments** (applied after subscores): weak liquidity, weak relative strength vs QQQ, earnings proximity, high volatility. First 3 flags are free; each additional flag costs −2.

**Tiers** (`"buy-review"` / `"watchlist"` / `"avoid/high-risk"`): thresholds are tunable via `TierThresholds`. The walk-forward tuning loop in `tuning/` proposes updated thresholds; `scripts/apply_tuning_proposal.py --write` commits them after manual review.

**Regime gate**: if QQQ is below its 20d MA **and** 20d return is negative, the watchlist output is capped at 3 candidates regardless of score.

## Architecture: Key Abstractions

**Protocol-based DI**: `UniverseProvider`, `MarketDataProvider`, `IndicatorEngine`, `CandidateScorer` are `runtime_checkable` Protocols. Implementations are swapped via factory functions (`build_market_data_provider(settings)`, `build_earnings_calendar_provider(settings)`) so no consumer constructs providers directly.

**`PipelineContext`**: immutable run metadata (date, output_dir, dry_run flag) threaded through every step. Dry-run skips all writes but executes scoring normally.

**`Settings`**: resolved from env vars with OpenClaw secrets (`~/.openclaw/secrets.json`) as fallback. Relevant vars: `TWELVE_DATA_API_KEY`, `ORACLE_DB_*`, `SCREENER_MARKET_DATA_PROVIDER`, `SCREENER_DAILY_INTRADAY_SOURCE_MODE`, `SCREENER_EARNINGS_CALENDAR_PATH`, `SCREENER_ORACLE_SQL_ENABLED`.

**Alert state machine** (`alerts/`): `AlertState` tracks prior tier/score/rank per ticker. `determine_change_status()` classifies events as `new` / `upgraded` / `downgraded` / `same`. `alert-events.json` under `output/daily/latest/` is the stable consumer entrypoint. Quality gate (`evaluate_daily_quality_gate()`) blocks alert emission if >20 tickers failed data fetch or >10 date mismatches.

**Indicator snapshot versioning**: `INDICATOR_SNAPSHOT_SCHEMA_VERSION = 2` in `models/schemas.py`; bump when adding/removing snapshot keys to avoid silently misaligning alert consumers.

## Project Structure & Conventions

- `src/screener/cli/main.py` — Typer entrypoint; all CLI commands defined here.
- `src/screener/pipeline.py` — public facade; delegates to `_pipeline/` internals.
- `src/screener/_pipeline/` — daily-run steps (data fetch, indicator compute, scoring, reporting, alert building).
- `src/screener/scoring/` — ranking, tiering, thresholds; the core domain logic.
- `src/screener/indicators/technicals.py` — pure functions; no I/O, easily unit-testable.
- `src/screener/tuning/` — walk-forward grid search producing `TierThresholds` proposals.
- `scripts/` — cron-friendly wrappers; also `apply_tuning_proposal.py` for threshold promotion.
- `output/` — generated artifacts only; never edit manually.

Python 3.11+; `from __future__ import annotations` in every module header; `snake_case` for everything except `PascalCase` classes/models. Prefer deterministic functions; isolate all I/O behind `storage/` and runner boundaries.

## Testing Conventions

Mirror production surface: CLI changes → `tests/test_cli.py`, pipeline logic → `tests/test_pipeline.py`, provider/storage → matching module test. Use stubs and `monkeypatch`; no live API or Oracle calls in tests. Commit style: `feat: ...` / `fix: ...` / `docs: ...`, imperative mood, one logical change per commit.
