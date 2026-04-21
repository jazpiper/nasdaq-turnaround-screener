from __future__ import annotations

from pathlib import Path

from screener.backtest import HistoricalBacktestRunner
from screener.config import Settings
from screener.models import TickerInput
from screener.pipeline import RankedCandidateScorer, TechnicalIndicatorEngine, YFinanceMarketDataProvider
from tests.test_pipeline import StubFetcher, make_bars_from_history, make_benchmark_provider, make_history


class SingleTickerUniverse:
    def load_universe(self, context):
        return [TickerInput(ticker="AAPL")]


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
    assert "forward_return_5d" in artifacts.observations_path.read_text(encoding="utf-8")
