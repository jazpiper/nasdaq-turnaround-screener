from __future__ import annotations

from pathlib import Path
from typing import Any

from screener.backtest import HistoricalBacktestRunner
from screener.config import Settings
from screener.models import CandidateResult, PipelineContext, TickerInput
from screener.pipeline import RankedCandidateScorer, TechnicalIndicatorEngine, YFinanceMarketDataProvider
from tests.test_pipeline import StubFetcher, make_bars_from_history, make_benchmark_provider, make_history


class SingleTickerUniverse:
    def load_universe(self, context):
        return [TickerInput(ticker="AAPL")]


class TrackingUniverse:
    def __init__(self) -> None:
        self.contexts: list[PipelineContext] = []

    def load_universe(self, context: PipelineContext) -> list[TickerInput]:
        self.contexts.append(context)
        return [TickerInput(ticker="AAPL")]


class TrackingMarketDataProvider:
    def __init__(self, history) -> None:
        self.history = history
        self.contexts: list[PipelineContext] = []

    def prepare(self, tickers: list[TickerInput], context: PipelineContext) -> None:
        self.contexts.append(context)

    def fetch_history(self, ticker: TickerInput, context: PipelineContext):
        self.contexts.append(context)
        return self.history


class TrackingIndicatorEngine:
    def __init__(self) -> None:
        self.contexts: list[PipelineContext] = []

    def compute(self, history, ticker: TickerInput, context: PipelineContext) -> dict[str, Any]:
        self.contexts.append(context)
        return {"stock_return_20d": 1.0, "stock_return_60d": 2.0}


class TrackingScorer:
    def __init__(self, indicator_snapshot: dict[str, object] | None = None) -> None:
        self.indicator_snapshot = indicator_snapshot
        self.contexts: list[PipelineContext] = []

    def evaluate(
        self,
        ticker: TickerInput,
        indicators: dict[str, Any],
        context: PipelineContext,
    ) -> CandidateResult:
        self.contexts.append(context)
        return CandidateResult(
            ticker=ticker.ticker,
            score=42,
            tier="watchlist",
            reasons=["reason"],
            risks=["risk"],
            indicator_snapshot=self.indicator_snapshot,
            generated_at=context.generated_at,
        )


def _tracking_runner(*, settings_output_dir: Path, indicator_snapshot: dict[str, object] | None = None):
    history = make_history(start_close=180.0, days=90)
    universe = TrackingUniverse()
    market_data = TrackingMarketDataProvider(history)
    benchmark_market_data = TrackingMarketDataProvider(make_history(start_close=500.0, days=90, decline_step=0.2))
    indicator_engine = TrackingIndicatorEngine()
    scorer = TrackingScorer(indicator_snapshot=indicator_snapshot)
    runner = HistoricalBacktestRunner(
        settings=Settings(output_dir=settings_output_dir),
        universe_provider=universe,
        market_data_provider=market_data,
        indicator_engine=indicator_engine,
        candidate_scorer=scorer,
        benchmark_market_data_provider=benchmark_market_data,
    )
    run_date = history.iloc[-10]["date"]
    return runner, run_date, (universe, market_data, benchmark_market_data, indicator_engine, scorer)


def _all_output_dirs(trackers: tuple[object, ...]) -> set[Path]:
    output_dirs: set[Path] = set()
    for tracker in trackers:
        output_dirs.update(context.output_dir for context in tracker.contexts)
    return output_dirs


def test_generate_observations_uses_settings_output_dir_for_pipeline_contexts(tmp_path: Path) -> None:
    settings_output_dir = tmp_path / "settings-output"
    runner, run_date, trackers = _tracking_runner(
        settings_output_dir=settings_output_dir,
        indicator_snapshot={},
    )

    observations, data_failures, trading_day_count = runner.generate_observations(
        start_date=run_date,
        end_date=run_date,
        forward_horizons=(5,),
    )

    assert len(observations) == 1
    assert data_failures == []
    assert trading_day_count == 1
    assert _all_output_dirs(trackers) == {settings_output_dir}


def test_run_uses_caller_output_dir_for_pipeline_contexts(tmp_path: Path) -> None:
    settings_output_dir = tmp_path / "settings-output"
    caller_output_dir = tmp_path / "caller-output"
    runner, run_date, trackers = _tracking_runner(
        settings_output_dir=settings_output_dir,
        indicator_snapshot={},
    )

    summary, artifacts = runner.run(
        start_date=run_date,
        end_date=run_date,
        output_dir=caller_output_dir,
        forward_horizons=(5,),
        dry_run=True,
    )

    assert summary["candidate_observation_count"] == 1
    assert artifacts.summary_path is None
    assert _all_output_dirs(trackers) == {caller_output_dir}


def test_generate_observations_handles_default_subscores_and_missing_snapshot(tmp_path: Path) -> None:
    runner, run_date, _trackers = _tracking_runner(
        settings_output_dir=tmp_path,
        indicator_snapshot=None,
    )

    observations, data_failures, trading_day_count = runner.generate_observations(
        start_date=run_date,
        end_date=run_date,
        forward_horizons=(5,),
    )

    assert data_failures == []
    assert trading_day_count == 1
    assert len(observations) == 1
    assert observations[0].snapshot == {}
    assert observations[0].subscores == {
        "oversold": 0,
        "bottom_context": 0,
        "reversal": 0,
        "volume": 0,
        "market_context": 0,
    }


def test_historical_backtest_runner_writes_summary_and_observations(tmp_path: Path) -> None:
    history = make_history(start_close=180.0, days=90)
    provider = YFinanceMarketDataProvider(
        fetcher=StubFetcher({"AAPL": make_bars_from_history("AAPL", history)})
    )
    runner = HistoricalBacktestRunner(
        settings=Settings(output_dir=tmp_path),
        universe_provider=SingleTickerUniverse(),
        market_data_provider=provider,
        indicator_engine=TechnicalIndicatorEngine(),
        candidate_scorer=RankedCandidateScorer(),
        benchmark_market_data_provider=make_benchmark_provider(),
    )

    start_date = history.iloc[-8]["date"]
    end_date = history.iloc[-6]["date"]
    summary, artifacts = runner.run(
        start_date=start_date,
        end_date=end_date,
        output_dir=tmp_path,
        forward_horizons=(5,),
        dry_run=False,
    )

    assert summary["trading_day_count"] >= 1
    assert summary["candidate_observation_count"] >= 1
    assert artifacts.summary_path == tmp_path / "backtest-summary.json"
    assert artifacts.observations_path == tmp_path / "backtest-observations.csv"
    assert artifacts.summary_path.exists()
    assert artifacts.observations_path.exists()
    observation_csv = artifacts.observations_path.read_text(encoding="utf-8")
    assert "tier" in observation_csv
    assert "forward_return_5d" in observation_csv
    assert "benchmark_forward_return_5d" in observation_csv
    assert "excess_return_5d" in observation_csv
    assert "tier_forward_return_summary" in summary
    assert "score_cutoff_forward_return_summary" in summary
    assert "daily_top_n_forward_return_summary" in summary
    assert summary["forward_return_summary"]["5d"]["excess_count"] >= 0
    assert summary["forward_return_summary"]["5d"]["count"] >= summary["forward_return_summary"]["5d"]["excess_count"]
