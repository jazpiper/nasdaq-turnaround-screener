from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from screener.config import Settings
from screener.models import TickerInput
from screener.pipeline import (
    RankedCandidateScorer,
    ScreenPipeline,
    StaticUniverseProvider,
    TechnicalIndicatorEngine,
    YFinanceMarketDataProvider,
    build_context,
    build_market_data_provider,
)


def make_history(*, start_close: float, days: int = 90, final_volume: float = 1_500_000.0) -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows: list[dict[str, float | date]] = []
    close = start_close
    for day in range(days):
        if day < days - 3:
            close -= 0.4
        else:
            close += 0.01
        rows.append(
            {
                "date": start + timedelta(days=day),
                "open": close + 0.2,
                "high": close + 0.6,
                "low": close - 0.8,
                "close": close,
                "adj_close": close,
                "volume": final_volume if day == days - 1 else 1_200_000.0,
            }
        )
    return pd.DataFrame(rows)


class StubFetcher:
    def __init__(self, bars_by_ticker, failed_tickers=None):
        self.bars_by_ticker = bars_by_ticker
        self.failed_tickers = failed_tickers or {}

    def fetch(self, tickers):
        requested = tuple(tickers)
        return type(
            "FetchResult",
            (),
            {
                "bars_by_ticker": {ticker: self.bars_by_ticker[ticker] for ticker in requested if ticker in self.bars_by_ticker},
                "failed_tickers": {ticker: self.failed_tickers[ticker] for ticker in requested if ticker in self.failed_tickers},
            },
        )()


def make_bars_from_history(ticker: str, history: pd.DataFrame):
    return [
        type(
            "Bar",
            (),
            {
                "ticker": ticker,
                "trading_date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "adj_close": row.adj_close,
                "volume": row.volume,
            },
        )()
        for row in history.itertuples(index=False)
    ]


class StubUniverseProvider:
    def load_universe(self, context):
        return [TickerInput(ticker="AAPL"), TickerInput(ticker="MSFT"), TickerInput(ticker="NVDA")]


def test_static_universe_provider_loads_real_universe() -> None:
    context = build_context(run_date=date(2026, 4, 21), dry_run=True)
    tickers = StaticUniverseProvider().load_universe(context)
    assert len(tickers) >= 100
    assert tickers[0].ticker


def test_pipeline_runs_end_to_end_and_records_failures(tmp_path: Path) -> None:
    histories = {
        "AAPL": make_bars_from_history("AAPL", make_history(start_close=180.0)),
        "MSFT": make_bars_from_history("MSFT", make_history(start_close=420.0, final_volume=2_000_000.0)),
    }
    provider = YFinanceMarketDataProvider(
        fetcher=StubFetcher(histories, failed_tickers={"NVDA": "No price rows returned"})
    )
    settings = Settings(output_dir=tmp_path)
    pipeline = ScreenPipeline(
        settings=settings,
        universe_provider=StubUniverseProvider(),
        market_data_provider=provider,
        indicator_engine=TechnicalIndicatorEngine(),
        candidate_scorer=RankedCandidateScorer(),
    )
    context = build_context(
        run_date=date(2026, 4, 21),
        generated_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
        output_dir=tmp_path,
    )

    result, artifacts = pipeline.run(context)

    assert result.candidate_count >= 1
    assert any(candidate.ticker == "AAPL" for candidate in result.candidates)
    assert result.metadata.data_failures == ["NVDA: No price rows returned"]
    assert artifacts.markdown_path == tmp_path / "daily-report.md"
    assert artifacts.json_report_path == tmp_path / "daily-report.json"
    assert artifacts.metadata_path == tmp_path / "run-metadata.json"
    assert artifacts.markdown_path.exists()
    assert "Data Failures" in artifacts.markdown_path.read_text(encoding="utf-8")


def test_build_market_data_provider_uses_settings_choice() -> None:
    provider = build_market_data_provider(Settings(market_data_provider="twelve-data", twelve_data_api_key="secret"))

    assert provider.fetcher.provider_name == "twelve-data"
    assert provider.fetcher.api_key == "secret"


def test_pipeline_dry_run_skips_writes(tmp_path: Path) -> None:
    histories = {
        "AAPL": make_bars_from_history("AAPL", make_history(start_close=180.0)),
    }
    pipeline = ScreenPipeline(
        settings=Settings(output_dir=tmp_path),
        universe_provider=type("SingleTickerUniverse", (), {"load_universe": lambda self, context: [TickerInput(ticker="AAPL")]})(),
        market_data_provider=YFinanceMarketDataProvider(fetcher=StubFetcher(histories)),
        indicator_engine=TechnicalIndicatorEngine(),
        candidate_scorer=RankedCandidateScorer(),
    )
    context = build_context(run_date=date(2026, 4, 21), dry_run=True, output_dir=tmp_path)

    result, artifacts = pipeline.run(context)

    assert result.candidate_count >= 1
    assert artifacts.markdown_path is None
    assert not tmp_path.exists() or not any(tmp_path.iterdir())
