from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from screener.collector import TwelveDataWindowCollector
from screener.config import Settings
from screener.data.market_data import DailyBar, FetchResult


class StubFetcher:
    def fetch(self, tickers: list[str]) -> FetchResult:
        ticker = tickers[0]
        if ticker == "ABNB":
            return FetchResult(bars_by_ticker={}, failed_tickers={ticker: "provider error"})
        return FetchResult(
            bars_by_ticker={
                ticker: [
                    DailyBar(
                        ticker=ticker,
                        trading_date=date(2026, 4, 21),
                        open=100.0,
                        high=101.0,
                        low=99.0,
                        close=100.5,
                        adj_close=100.5,
                        volume=1000.0,
                    )
                ]
            },
            failed_tickers={},
        )


def build_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        output_dir=tmp_path,
        market_data_provider="twelve-data",
        twelve_data_api_key="secret",
    )
    return settings


def test_build_plan_evenly_splits_nasdaq_100_windows(tmp_path: Path) -> None:
    collector = TwelveDataWindowCollector(settings=build_settings(tmp_path))

    plans = [collector.build_plan(window_index=index) for index in range(6)]

    assert [len(plan.window_tickers) for plan in plans] == [17, 17, 17, 17, 16, 16]
    assert plans[0].window_tickers[:3] == ["AAPL", "ABNB", "ADBE"]
    assert plans[-1].window_tickers[-2:] == ["WDAY", "XEL"]
    assert sum(len(plan.window_tickers) for plan in plans) == 100


def test_build_plan_creates_minute_batches_capped_by_credit_budget(tmp_path: Path) -> None:
    collector = TwelveDataWindowCollector(
        settings=build_settings(tmp_path),
        universe=[f"T{index:02d}" for index in range(17)],
    )

    plan = collector.build_plan(window_index=0, total_windows=1, max_credits_per_minute=8)

    assert plan.minute_batches == [
        [f"T{index:02d}" for index in range(8)],
        [f"T{index:02d}" for index in range(8, 16)],
        ["T16"],
    ]


def test_run_window_writes_metadata_and_quotes(tmp_path: Path) -> None:
    sleep_calls: list[float] = []
    collector = TwelveDataWindowCollector(
        settings=build_settings(tmp_path),
        fetcher=StubFetcher(),
        sleeper=sleep_calls.append,
        clock=lambda: datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc),
        universe=["AAPL", "ABNB", "ADBE"],
    )

    result = collector.run_window(
        run_date=date(2026, 4, 21),
        output_root=tmp_path,
        window_index=0,
        total_windows=1,
        max_credits_per_minute=2,
    )

    assert result.successes == ["AAPL", "ADBE"]
    assert result.failures == {"ABNB": "provider error"}
    assert sleep_calls == [30, 30]
    assert result.artifacts.metadata_path is not None
    assert result.artifacts.quotes_path is not None

    metadata = json.loads(result.artifacts.metadata_path.read_text(encoding="utf-8"))
    assert metadata["planned_tickers"] == ["AAPL", "ABNB", "ADBE"]
    assert metadata["successes"] == ["AAPL", "ADBE"]
    assert metadata["failures"] == {"ABNB": "provider error"}
    assert metadata["uncollected_tickers"] == ["ABNB"]
    assert metadata["remaining_tickers"] == []

    quotes = json.loads(result.artifacts.quotes_path.read_text(encoding="utf-8"))
    assert [quote["ticker"] for quote in quotes["quotes"]] == ["AAPL", "ADBE"]
