from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from statistics import fmean
from typing import Any

import pandas as pd

from screener._pipeline.context import BENCHMARK_TICKER, _percent_return, merge_benchmark_context, merge_earnings_context
from screener._pipeline.core import RankedCandidateScorer, build_context
from screener._pipeline.contracts import CandidateScorer, IndicatorEngine, MarketDataProvider, UniverseProvider
from screener._pipeline.providers import (
    StaticUniverseProvider,
    TechnicalIndicatorEngine,
    build_earnings_calendar_provider,
    build_market_data_provider,
)
from screener.config import Settings
from screener.data import EarningsCalendarProvider
from screener.models import TickerInput
from screener.storage.files import write_json, write_text

DEFAULT_FORWARD_HORIZONS = (5, 10, 20)


@dataclass(frozen=True, slots=True)
class BacktestObservation:
    run_date: date
    ticker: str
    score: int
    reasons: list[str]
    risks: list[str]
    forward_returns: dict[int, float | None]

    def as_row(self, forward_horizons: tuple[int, ...]) -> dict[str, Any]:
        row: dict[str, Any] = {
            "run_date": self.run_date.isoformat(),
            "ticker": self.ticker,
            "score": self.score,
            "reasons": " | ".join(self.reasons),
            "risks": " | ".join(self.risks),
        }
        for horizon in forward_horizons:
            row[f"forward_return_{horizon}d"] = self.forward_returns.get(horizon)
        return row


@dataclass(frozen=True, slots=True)
class BacktestArtifacts:
    summary_path: Path | None = None
    observations_path: Path | None = None


class HistoricalBacktestRunner:
    def __init__(
        self,
        settings: Settings,
        universe_provider: UniverseProvider | None = None,
        market_data_provider: MarketDataProvider | None = None,
        indicator_engine: IndicatorEngine | None = None,
        candidate_scorer: CandidateScorer | None = None,
        earnings_calendar_provider: EarningsCalendarProvider | None = None,
        benchmark_market_data_provider: MarketDataProvider | None = None,
    ) -> None:
        self.settings = settings
        self.universe_provider = universe_provider or StaticUniverseProvider()
        self.market_data_provider = market_data_provider or build_market_data_provider(settings)
        self.indicator_engine = indicator_engine or TechnicalIndicatorEngine()
        self.candidate_scorer = candidate_scorer or RankedCandidateScorer()
        self.earnings_calendar_provider = earnings_calendar_provider or build_earnings_calendar_provider(settings)
        self.benchmark_market_data_provider = benchmark_market_data_provider or build_market_data_provider(settings)

    def run(
        self,
        *,
        start_date: date,
        end_date: date,
        output_dir: Path,
        forward_horizons: tuple[int, ...] = DEFAULT_FORWARD_HORIZONS,
        dry_run: bool = False,
    ) -> tuple[dict[str, Any], BacktestArtifacts]:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        base_context = build_context(
            run_date=end_date,
            dry_run=True,
            output_dir=output_dir,
            run_mode="backtest",
            universe_name=self.settings.universe_name,
        )
        tickers = self.universe_provider.load_universe(base_context)
        histories = self._load_histories(tickers, base_context)
        benchmark_history = self._load_benchmark_history(base_context)
        trading_dates = [
            trading_date
            for trading_date in benchmark_history.sort_values("date")["date"].tolist()
            if start_date <= trading_date <= end_date
        ]

        observations: list[BacktestObservation] = []
        data_failures: list[str] = []
        for run_date in trading_dates:
            run_context = build_context(
                run_date=run_date,
                generated_at=base_context.generated_at,
                dry_run=True,
                output_dir=output_dir,
                run_mode="backtest",
                universe_name=base_context.universe_name,
            )
            benchmark_context = _benchmark_context_for_date(benchmark_history, run_date)
            earnings_by_ticker = self._load_earnings(tickers, run_date, data_failures)
            for ticker in tickers:
                full_history = histories.get(ticker.ticker)
                if full_history is None:
                    continue

                history = _slice_history(full_history, run_date)
                if history.empty:
                    continue

                try:
                    indicators = self.indicator_engine.compute(history, ticker, run_context)
                    indicators = merge_benchmark_context(indicators, benchmark_context)
                    indicators = merge_earnings_context(indicators, earnings_by_ticker.get(ticker.ticker))
                    candidate = self.candidate_scorer.evaluate(ticker, indicators, run_context)
                except Exception as exc:  # pragma: no cover
                    data_failures.append(f"{run_date.isoformat()} {ticker.ticker}: {exc}")
                    continue

                if candidate is None:
                    continue

                observations.append(
                    BacktestObservation(
                        run_date=run_date,
                        ticker=candidate.ticker,
                        score=candidate.score,
                        reasons=list(candidate.reasons),
                        risks=list(candidate.risks),
                        forward_returns=_compute_forward_returns(full_history, run_date, forward_horizons),
                    )
                )

        observations.sort(key=lambda item: (item.run_date, -item.score, item.ticker))
        summary = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "trading_day_count": len(trading_dates),
            "candidate_observation_count": len(observations),
            "forward_horizons": list(forward_horizons),
            "forward_return_summary": _summarize_forward_returns(observations, forward_horizons),
            "data_failures": data_failures,
        }

        artifacts = BacktestArtifacts()
        if not dry_run:
            artifacts = self._write_artifacts(summary, observations, output_dir, forward_horizons)
        return summary, artifacts

    def _load_histories(self, tickers: list[TickerInput], context) -> dict[str, pd.DataFrame]:
        prepare = getattr(self.market_data_provider, "prepare", None)
        if callable(prepare):
            prepare(tickers, context)

        histories: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            histories[ticker.ticker] = self.market_data_provider.fetch_history(ticker, context).sort_values("date").reset_index(
                drop=True
            )
        return histories

    def _load_benchmark_history(self, context) -> pd.DataFrame:
        benchmark = TickerInput(ticker=BENCHMARK_TICKER)
        prepare = getattr(self.benchmark_market_data_provider, "prepare", None)
        if callable(prepare):
            prepare([benchmark], context)
        return self.benchmark_market_data_provider.fetch_history(benchmark, context).sort_values("date").reset_index(
            drop=True
        )

    def _load_earnings(
        self,
        tickers: list[TickerInput],
        run_date: date,
        data_failures: list[str],
    ) -> dict[str, Any]:
        if self.earnings_calendar_provider is None:
            return {}
        try:
            return self.earnings_calendar_provider.fetch([item.ticker for item in tickers], run_date)
        except Exception as exc:  # pragma: no cover
            data_failures.append(f"{run_date.isoformat()} earnings: {exc}")
            return {}

    def _write_artifacts(
        self,
        summary: dict[str, Any],
        observations: list[BacktestObservation],
        output_dir: Path,
        forward_horizons: tuple[int, ...],
    ) -> BacktestArtifacts:
        summary_path = write_json(output_dir / "backtest-summary.json", summary)
        observations_path = write_text(
            output_dir / "backtest-observations.csv",
            _build_observation_csv(observations, forward_horizons),
        )
        return BacktestArtifacts(summary_path=summary_path, observations_path=observations_path)


def _slice_history(history: pd.DataFrame, run_date: date) -> pd.DataFrame:
    return history[history["date"] <= run_date].copy()


def _benchmark_context_for_date(benchmark_history: pd.DataFrame, run_date: date) -> dict[str, Any]:
    closes = [float(value) for value in _slice_history(benchmark_history, run_date)["close"].tolist()]
    return {
        "qqq_return_20d": _percent_return(closes, 20),
        "qqq_return_60d": _percent_return(closes, 60),
    }


def _compute_forward_returns(
    history: pd.DataFrame,
    run_date: date,
    forward_horizons: tuple[int, ...],
) -> dict[int, float | None]:
    current_rows = history.index[history["date"] == run_date].tolist()
    if not current_rows:
        return {horizon: None for horizon in forward_horizons}

    base_index = current_rows[-1]
    base_close = float(history.iloc[base_index]["close"])
    if base_close == 0:
        return {horizon: None for horizon in forward_horizons}

    returns: dict[int, float | None] = {}
    for horizon in forward_horizons:
        target_index = base_index + horizon
        if target_index >= len(history):
            returns[horizon] = None
            continue
        future_close = float(history.iloc[target_index]["close"])
        returns[horizon] = ((future_close / base_close) - 1.0) * 100.0
    return returns


def _summarize_forward_returns(
    observations: list[BacktestObservation],
    forward_horizons: tuple[int, ...],
) -> dict[str, dict[str, float | int | None]]:
    summary: dict[str, dict[str, float | int | None]] = {}
    for horizon in forward_horizons:
        returns = [
            value
            for observation in observations
            if (value := observation.forward_returns.get(horizon)) is not None
        ]
        summary[f"{horizon}d"] = {
            "count": len(returns),
            "average_return_pct": round(fmean(returns), 4) if returns else None,
        }
    return summary


def _build_observation_csv(observations: list[BacktestObservation], forward_horizons: tuple[int, ...]) -> str:
    fieldnames = ["run_date", "ticker", "score", "reasons", "risks"] + [
        f"forward_return_{horizon}d" for horizon in forward_horizons
    ]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for observation in observations:
        writer.writerow(observation.as_row(forward_horizons))
    return buffer.getvalue()
