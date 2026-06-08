#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (SRC_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from screener.data import DailyBar, MarketDataFetcher, build_market_data_fetcher
from screener.recommendations import (
    DEFAULT_BENCHMARK_PRIMARY,
    DEFAULT_BENCHMARK_SECONDARY,
    initialize_recommendation_db,
    summarize_recommendation_outcomes,
    update_recommendation_outcomes,
)

DEFAULT_RECOMMENDATION_OUTPUT_DIR = PROJECT_ROOT / "output" / "recommendations-expanded"
DEFAULT_DB_PATH = DEFAULT_RECOMMENDATION_OUTPUT_DIR / "recommendations.sqlite3"
DEFAULT_MARKET_OHLC_PATH = DEFAULT_RECOMMENDATION_OUTPUT_DIR / "market-ohlc.json"
DEFAULT_SUMMARY_PATH = DEFAULT_RECOMMENDATION_OUTPUT_DIR / "outcome-summary.json"
DEFAULT_PROVIDER = "yfinance"


def _resolve_as_of_date(value: str | None) -> str:
    if value in (None, "", "today", "utc-today"):
        return datetime.now(timezone.utc).date().isoformat()
    if value == "ny-today":
        from screener.dates import resolve_ny_run_date

        return resolve_ny_run_date("ny-today")
    date.fromisoformat(value)
    return value


def _set_default_market_env() -> None:
    os.environ.setdefault("SCREENER_MARKET_DATA_PROVIDER", DEFAULT_PROVIDER)
    os.environ.setdefault("SCREENER_YFINANCE_BATCH_SIZE", "1")
    os.environ.setdefault("SCREENER_YFINANCE_BATCH_PAUSE_SECONDS", "1")
    os.environ.setdefault("SCREENER_YFINANCE_THREADS", "false")
    os.environ.setdefault("SCREENER_YFINANCE_DAILY_REQUEST_CAP", "750")
    os.environ.setdefault(
        "SCREENER_YFINANCE_QUOTA_STATE_PATH",
        str(PROJECT_ROOT / "output" / ".quota" / "yfinance-shared.json"),
    )


def _pending_recommendation_tickers(db_path: Path) -> list[str]:
    initialize_recommendation_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            select distinct upper(trim(r.ticker))
            from recommendation_outcomes o
            join recommendations r on r.recommendation_id = o.recommendation_id
            where o.outcome_status = 'pending'
              and r.ticker is not null
              and trim(r.ticker) != ''
            order by upper(trim(r.ticker))
            """
        ).fetchall()
    tickers = [str(row[0]) for row in rows]
    if not tickers:
        return []
    for benchmark in (DEFAULT_BENCHMARK_PRIMARY, DEFAULT_BENCHMARK_SECONDARY):
        if benchmark not in tickers:
            tickers.append(benchmark)
    return tickers


def _bar_payload(bar: DailyBar) -> dict[str, float]:
    return {
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "adj_close": float(bar.adj_close),
        "volume": float(bar.volume),
    }


def _write_market_ohlc(path: Path, bars_by_ticker: dict[str, list[DailyBar]]) -> dict[str, dict[str, dict[str, float]]]:
    payload: dict[str, dict[str, dict[str, float]]] = {}
    for ticker, bars in sorted(bars_by_ticker.items()):
        payload[ticker] = {
            bar.trading_date.isoformat(): _bar_payload(bar)
            for bar in sorted(bars, key=lambda item: item.trading_date)
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def run_outcome_update(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    market_ohlc_path: Path = DEFAULT_MARKET_OHLC_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    as_of_date: str | None = None,
    fetcher: MarketDataFetcher | None = None,
) -> dict[str, Any]:
    resolved_as_of_date = _resolve_as_of_date(as_of_date)
    tickers = _pending_recommendation_tickers(db_path)
    if not tickers:
        summary = summarize_recommendation_outcomes(db_path=db_path, output_path=summary_path)
        return {
            "message": "No pending recommendation outcomes.",
            "as_of_date": resolved_as_of_date,
            "pending_ticker_count": 0,
            "summary_path": str(summary_path),
            "summary_algorithm_count": len(summary.get("algorithm_versions", [])),
        }

    _set_default_market_env()
    resolved_fetcher = fetcher or build_market_data_fetcher(provider=os.getenv("SCREENER_MARKET_DATA_PROVIDER", DEFAULT_PROVIDER))
    fetch_result = resolved_fetcher.fetch(tickers)
    price_payload = _write_market_ohlc(market_ohlc_path, fetch_result.bars_by_ticker)
    update_result = update_recommendation_outcomes(
        db_path=db_path,
        prices_by_ticker=price_payload,
        as_of_date=resolved_as_of_date,
    )
    summary = summarize_recommendation_outcomes(db_path=db_path, output_path=summary_path)
    return {
        "message": "Recommendation outcomes updated.",
        "as_of_date": resolved_as_of_date,
        "pending_ticker_count": len(tickers),
        "fetched_ticker_count": len(fetch_result.bars_by_ticker),
        "failed_ticker_count": len(fetch_result.failed_tickers),
        "failed_tickers": fetch_result.failed_tickers,
        "source_statuses": fetch_result.source_statuses,
        "market_ohlc_path": str(market_ohlc_path),
        "summary_path": str(summary_path),
        "summary_algorithm_count": len(summary.get("algorithm_versions", [])),
        **update_result,
    }


def _format_report(result: dict[str, Any]) -> str:
    lines = [
        f"NASDAQ recommendation outcome update ({result.get('as_of_date')})",
        f"- status: {result.get('message')}",
        f"- pending tickers checked: {result.get('pending_ticker_count', 0)}",
    ]
    if "fetched_ticker_count" in result:
        lines.extend(
            [
                f"- fetched tickers: {result.get('fetched_ticker_count', 0)}",
                f"- failed tickers: {result.get('failed_ticker_count', 0)}",
                f"- settled outcomes: {result.get('settled_outcomes', 0)}",
                f"- no-fill outcomes: {result.get('no_fill_outcomes', 0)}",
                f"- still pending outcomes: {result.get('pending_outcomes', 0)}",
            ]
        )
    if result.get("failed_tickers"):
        failed = result["failed_tickers"]
        preview = ", ".join(f"{ticker}: {reason}" for ticker, reason in list(failed.items())[:5])
        lines.append(f"- failures: {preview}")
    if result.get("summary_path"):
        lines.append(f"- summary: {result['summary_path']}")
    if result.get("market_ohlc_path"):
        lines.append(f"- market OHLC: {result['market_ohlc_path']}")
    lines.append("- safety: advisory outcome tracking only; no orders or broker API calls.")
    return "\n".join(lines)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch OHLC data and settle pending recommendation outcomes.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--market-ohlc-path", type=Path, default=DEFAULT_MARKET_OHLC_PATH)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--as-of-date", default="ny-today", help="YYYY-MM-DD, today/utc-today, or ny-today")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_outcome_update(
        db_path=args.db_path,
        market_ohlc_path=args.market_ohlc_path,
        summary_path=args.summary_path,
        as_of_date=args.as_of_date,
    )
    print(_format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
