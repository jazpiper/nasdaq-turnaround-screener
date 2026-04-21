from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from screener.config import Settings
from screener.data.earnings import EarningsInfo
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


def make_history(*, start_close: float, days: int = 90, final_volume: float = 1_500_000.0, rebound_days: int = 3, rebound_step: float = 0.01, decline_step: float = 0.4) -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows: list[dict[str, float | date]] = []
    close = start_close
    for day in range(days):
        if day < days - rebound_days:
            close -= decline_step
        else:
            close += rebound_step
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


def make_benchmark_provider() -> YFinanceMarketDataProvider:
    return YFinanceMarketDataProvider(
        fetcher=StubFetcher({"QQQ": make_bars_from_history("QQQ", make_history(start_close=500.0, decline_step=0.2))})
    )


class StubUniverseProvider:
    def load_universe(self, context):
        return [TickerInput(ticker="AAPL"), TickerInput(ticker="MSFT"), TickerInput(ticker="NVDA")]


class StubEarningsProvider:
    def fetch(self, tickers, run_date):
        return {
            "AAPL": EarningsInfo(
                next_earnings_date=date(2026, 4, 23),
                days_to_next_earnings=2,
                days_since_last_earnings=40,
            )
        }


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
        earnings_calendar_provider=StubEarningsProvider(),
        benchmark_market_data_provider=make_benchmark_provider(),
    )
    context = build_context(
        run_date=date(2026, 4, 21),
        generated_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
        output_dir=tmp_path,
    )

    result, artifacts = pipeline.run(context)

    assert result.candidate_count >= 1
    assert any(candidate.ticker == "AAPL" for candidate in result.candidates)
    candidate = next(candidate for candidate in result.candidates if candidate.ticker == "AAPL")
    assert candidate.indicator_snapshot is not None
    assert candidate.indicator_snapshot["schema_version"] == 2
    assert candidate.indicator_snapshot["earnings_data_available"] is True
    assert candidate.indicator_snapshot["days_to_next_earnings"] == 2
    assert candidate.indicator_snapshot["earnings_penalty"] == 8
    assert candidate.indicator_snapshot["volatility_penalty"] == 0
    assert "atr_14" in candidate.indicator_snapshot
    assert "atr_14_pct" in candidate.indicator_snapshot
    assert "daily_range_pct" in candidate.indicator_snapshot
    assert "bb_width_pct" in candidate.indicator_snapshot
    assert "close_above_open" in candidate.indicator_snapshot
    assert "close_location_value" in candidate.indicator_snapshot
    assert "lower_wick_ratio" in candidate.indicator_snapshot
    assert "gap_down_pct" in candidate.indicator_snapshot
    assert "gap_down_reclaim" in candidate.indicator_snapshot
    assert "rel_strength_20d_vs_qqq" in candidate.indicator_snapshot
    assert "relative_strength_score" in candidate.indicator_snapshot
    assert "volume_ratio_20d" in candidate.indicator_snapshot
    assert "weekly_trend_penalty" in candidate.indicator_snapshot
    assert "실적 발표가 임박해 이벤트 리스크가 큼" in candidate.risks
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


def test_pipeline_sets_earnings_data_unavailable_when_provider_missing(tmp_path: Path) -> None:
    histories = {
        "AAPL": make_bars_from_history("AAPL", make_history(start_close=180.0)),
    }
    pipeline = ScreenPipeline(
        settings=Settings(output_dir=tmp_path),
        universe_provider=type("SingleTickerUniverse", (), {"load_universe": lambda self, context: [TickerInput(ticker="AAPL")]})(),
        market_data_provider=YFinanceMarketDataProvider(fetcher=StubFetcher(histories)),
        indicator_engine=TechnicalIndicatorEngine(),
        candidate_scorer=RankedCandidateScorer(),
        benchmark_market_data_provider=make_benchmark_provider(),
    )

    result, _ = pipeline.run(build_context(run_date=date(2026, 4, 21), dry_run=True, output_dir=tmp_path))

    candidate = result.candidates[0]
    assert candidate.indicator_snapshot is not None
    assert candidate.indicator_snapshot["earnings_data_available"] is False


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
        benchmark_market_data_provider=make_benchmark_provider(),
    )
    context = build_context(run_date=date(2026, 4, 21), dry_run=True, output_dir=tmp_path)

    result, artifacts = pipeline.run(context)

    assert result.candidate_count >= 1
    assert artifacts.markdown_path is None
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


def test_indicator_engine_includes_weekly_context_and_penalty() -> None:
    history = make_history(start_close=180.0, days=90, rebound_days=2, rebound_step=-0.2)
    indicators = TechnicalIndicatorEngine().compute(
        history,
        TickerInput(ticker="AAPL"),
        build_context(run_date=date(2026, 4, 21), dry_run=True),
    )

    assert indicators["weekly_bars_available"] >= 10
    assert indicators["weekly_sma_10"] is not None
    assert indicators["weekly_trend_penalty"] >= 3.0


def test_indicator_engine_includes_volatility_metrics() -> None:
    history = make_history(start_close=180.0, days=90)
    indicators = TechnicalIndicatorEngine().compute(
        history,
        TickerInput(ticker="AAPL"),
        build_context(run_date=date(2026, 4, 21), dry_run=True),
    )

    assert indicators["atr_14"] is not None
    assert indicators["atr_14_pct"] is not None
    assert indicators["daily_range_pct"] is not None
    assert indicators["bb_width_pct"] is not None
    assert indicators["atr_14_pct"] > 0
    assert indicators["daily_range_pct"] > 0


def test_indicator_engine_includes_candle_structure_metrics() -> None:
    history = make_history(start_close=180.0, days=90)
    indicators = TechnicalIndicatorEngine().compute(
        history,
        TickerInput(ticker="AAPL"),
        build_context(run_date=date(2026, 4, 21), dry_run=True),
    )

    assert isinstance(indicators["close_above_open"], bool)
    assert indicators["close_location_value"] is not None
    assert indicators["lower_wick_ratio"] is not None
    assert indicators["gap_down_pct"] is not None
    assert isinstance(indicators["gap_down_reclaim"], bool)


def test_pipeline_rejects_candidate_when_weekly_trend_damage_is_severe(tmp_path: Path) -> None:
    history = make_history(start_close=260.0, days=90, rebound_days=1, rebound_step=-1.5, decline_step=1.5)
    pipeline = ScreenPipeline(
        settings=Settings(output_dir=tmp_path),
        universe_provider=type("SingleTickerUniverse", (), {"load_universe": lambda self, context: [TickerInput(ticker="AAPL")]})(),
        market_data_provider=YFinanceMarketDataProvider(fetcher=StubFetcher({"AAPL": make_bars_from_history("AAPL", history)})),
        indicator_engine=TechnicalIndicatorEngine(),
        candidate_scorer=RankedCandidateScorer(),
        benchmark_market_data_provider=make_benchmark_provider(),
    )

    result, _ = pipeline.run(build_context(run_date=date(2026, 4, 21), dry_run=True, output_dir=tmp_path))

    assert result.candidate_count == 0
