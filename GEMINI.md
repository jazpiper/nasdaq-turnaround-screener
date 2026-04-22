# Gemini Context: NASDAQ Turnaround Screener

This project is a personal research screener designed to scan NASDAQ-100 stocks for oversold conditions and early reversal signals. It is built as a batch research tool rather than an automated trading system.

## Project Overview

- **Purpose:** Daily research tool for identifying "turnaround" candidates in the NASDAQ-100.
- **Key Technologies:**
  - **Language:** Python 3.11+
  - **Build System:** [Hatchling](https://hatch.pypa.io/)
  - **CLI Framework:** [Typer](https://typer.tiangolo.com/)
  - **Data Processing:** Pandas, NumPy
  - **Data Validation:** Pydantic V2
  - **Market Data:** `yfinance` (Daily), Twelve Data (Intraday)
  - **Persistence:** File-based (JSON/Markdown) and Oracle SQL (opt-in)
- **Architecture:**
  - **Pipeline:** Orchestrated daily runs involving universe loading, data fetching, indicator calculation, and scoring.
  - **Staged Intraday:** Throttled collection for intraday snapshots to enrich daily runs.
  - **Indicators:** Technical analysis including Bollinger Bands, RSI, SMA, ATR, and candle structure.
  - **Scoring:** Multi-factor scoring (Oversold, Bottom Context, Reversal, Volume, Market Context, Candle Structure) with independent Earnings and Volatility overlay penalties.

## Building and Running

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### Key Commands
- **Run Daily Screener:**
  ```bash
  python -m screener.cli.main run --date 2026-04-22
  ```
- **Intraday Collection:**
  ```bash
  python -m screener.cli.main collect-window --date 2026-04-22 --window-index 0 --total-windows 1
  ```
- **Initialize Database:**
  ```bash
  python -m screener.cli.main init-oracle-schema
  ```
- **Run Backtest:**
  ```bash
  python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-22
  ```

### Testing
```bash
pytest
```

## Development Conventions

- **Type Safety:** Strict use of Python type hints and `from __future__ import annotations`.
- **Data Modeling:** All major data structures (Metadata, Results, Context) are defined using Pydantic models in `src/screener/models/schemas.py`.
- **Interface Segregation:** Core pipeline components use abstract base classes (Contracts) defined in `src/screener/_pipeline/contracts.py`.
- **Configuration:** Managed via `src/screener/config.py`, supporting environment variables and OpenClaw secrets.
- **Reporting:** Outputs are generated as both human-readable Markdown and machine-readable JSON in the `output/` directory.
- **Indicators & Scoring:**
  - Indicators are calculated in `src/screener/indicators/technicals.py`.
  - Scoring logic and thresholds are maintained in `src/screener/scoring/`.

## Directory Structure
- `src/screener/_pipeline/`: Internal orchestration logic.
- `src/screener/data/`: Data providers and normalization.
- `src/screener/indicators/`: Technical analysis logic.
- `src/screener/scoring/`: Filtering and ranking algorithms.
- `src/screener/storage/`: Persistence layers (File, Oracle SQL).
- `scripts/`: Wrapper scripts for cron or automation.
- `docs/`: In-depth documentation on architecture, signals, and operations.
