#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TICKER_FILE = PROJECT_ROOT / "config" / "nasdaq-expanded-500.txt"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output" / "daily-nasdaq-expanded-500"
DEFAULT_RECOMMENDATION_OUTPUT_DIR = PROJECT_ROOT / "output" / "recommendations-expanded"
DEFAULT_RECOMMENDATION_DB = DEFAULT_RECOMMENDATION_OUTPUT_DIR / "recommendations.sqlite3"
DEFAULT_UNIVERSE_NAME = "nasdaq-expanded-500"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the isolated NASDAQ expanded-500 discovery lane.")
    parser.add_argument("--date", default="ny-today", help="Run date as YYYY-MM-DD, auto, or ny-today")
    parser.add_argument("--ticker-file", type=Path, default=DEFAULT_TICKER_FILE, help="Expanded ticker file")
    parser.add_argument("--limit", type=int, default=500, help="Ticker count when rebuilding the ticker file")
    parser.add_argument("--skip-install", action="store_true", help="Pass --skip-install to scripts/run_daily.py")
    parser.add_argument("--rebuild-tickers", action="store_true", help="Refresh the ticker file before running")
    parser.add_argument("--skip-recommendations", action="store_true", help="Only run the daily screener")
    parser.add_argument("--dry-run", action="store_true", help="Run daily screener without writing artifacts")
    return parser.parse_args()


def run(command: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("SCREENER_MARKET_DATA_PROVIDER", "yfinance")
    env.setdefault("SCREENER_YFINANCE_BATCH_SIZE", "1")
    env.setdefault("SCREENER_YFINANCE_BATCH_PAUSE_SECONDS", "1")
    env.setdefault("SCREENER_YFINANCE_THREADS", "false")
    env.setdefault("SCREENER_YFINANCE_DAILY_REQUEST_CAP", "750")
    env.setdefault("SCREENER_YFINANCE_QUOTA_STATE_PATH", str(PROJECT_ROOT / "output" / ".quota" / "yfinance-shared.json"))
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def ensure_ticker_file(path: Path, *, limit: int, rebuild: bool) -> None:
    if path.exists() and not rebuild:
        return
    run(
        [
            sys.executable,
            "scripts/build_nasdaq_expanded_tickers.py",
            "--output",
            str(path),
            "--limit",
            str(limit),
        ]
    )


def main() -> int:
    args = parse_args()
    ticker_file = args.ticker_file.expanduser().resolve()
    ensure_ticker_file(ticker_file, limit=args.limit, rebuild=args.rebuild_tickers)

    daily_command = [
        sys.executable,
        "scripts/run_daily.py",
        "--date",
        args.date,
        "--universe-name",
        DEFAULT_UNIVERSE_NAME,
        "--tickers-file",
        str(ticker_file),
        "--output-root",
        str(DEFAULT_OUTPUT_ROOT),
        "--skip-assistant-briefing",
    ]
    if args.skip_install:
        daily_command.append("--skip-install")
    if args.dry_run:
        daily_command.append("--dry-run")
    run(daily_command)

    if args.skip_recommendations or args.dry_run:
        return 0

    report_path = DEFAULT_OUTPUT_ROOT / "latest" / "daily-report.json"
    run(
        [
            sys.executable,
            "-m",
            "screener.cli.main",
            "build-daily-top3-recommendations",
            "--daily-report-path",
            str(report_path),
            "--db-path",
            str(DEFAULT_RECOMMENDATION_DB),
            "--output-dir",
            str(DEFAULT_RECOMMENDATION_OUTPUT_DIR),
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
