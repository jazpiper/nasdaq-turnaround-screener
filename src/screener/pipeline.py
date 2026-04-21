from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from screener.config import Settings
from screener.data import MarketDataFetcher, YFinanceDailyBarFetcher, build_market_data_fetcher
from screener.indicators.technicals import add_indicator_columns, rolling_mean
from screener.intraday_artifacts import discover_latest_intraday_snapshot, merge_history_with_staged_quote
from screener.models import (
    CandidateResult,
    PipelineContext,
    RunArtifacts,
    RunMetadata,
    ScoreBreakdown,
    ScreenRunResult,
    TickerInput,
)
from screener.reporting.json_report import build_json_report
from screener.reporting.markdown import build_markdown_report
from screener.scoring import rank_candidates
from screener.storage.files import ensure_directory, write_json, write_text
from screener.universe import load_static_universe


@runtime_checkable
class UniverseProvider(Protocol):
    def load_universe(self, context: PipelineContext) -> list[TickerInput]:
        """Return normalized ticker definitions for the requested run."""


@runtime_checkable
class MarketDataProvider(Protocol):
    def fetch_history(self, ticker: TickerInput, context: PipelineContext) -> pd.DataFrame:
        """Return normalized OHLCV history for a ticker."""


@runtime_checkable
class IndicatorEngine(Protocol):
    def compute(self, history: pd.DataFrame, ticker: TickerInput, context: PipelineContext) -> dict[str, Any]:
        """Compute indicator values from normalized history."""


@runtime_checkable
class CandidateScorer(Protocol):
    def evaluate(
        self,
        ticker: TickerInput,
        indicators: dict[str, Any],
        context: PipelineContext,
    ) -> CandidateResult | None:
        """Return a scored candidate, or None when the ticker does not qualify."""


class StaticUniverseProvider:
    def load_universe(self, context: PipelineContext) -> list[TickerInput]:
        definition = load_static_universe(name=context.universe_name)
        return [TickerInput(ticker=ticker) for ticker in definition.tickers]


class YFinanceMarketDataProvider:
    def __init__(self, fetcher: MarketDataFetcher | None = None) -> None:
        self.fetcher = fetcher or YFinanceDailyBarFetcher()
        self._history_by_ticker: dict[str, pd.DataFrame] = {}
        self._failures_by_ticker: dict[str, str] = {}
        self._prepared_tickers: tuple[str, ...] = ()

    def prepare(self, tickers: list[TickerInput], context: PipelineContext) -> None:
        ticker_symbols = tuple(ticker.ticker for ticker in tickers)
        if ticker_symbols == self._prepared_tickers:
            return

        fetch_result = self.fetcher.fetch(ticker_symbols)
        self._history_by_ticker = {
            ticker: pd.DataFrame(
                [
                    {
                        "date": bar.trading_date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "adj_close": bar.adj_close,
                        "volume": bar.volume,
                    }
                    for bar in bars
                ]
            )
            for ticker, bars in fetch_result.bars_by_ticker.items()
        }
        self._failures_by_ticker = dict(fetch_result.failed_tickers)
        self._prepared_tickers = ticker_symbols

    def fetch_history(self, ticker: TickerInput, context: PipelineContext) -> pd.DataFrame:
        if ticker.ticker in self._failures_by_ticker:
            raise RuntimeError(self._failures_by_ticker[ticker.ticker])

        history = self._history_by_ticker.get(ticker.ticker)
        if history is None:
            self.prepare([ticker], context)
            history = self._history_by_ticker.get(ticker.ticker)
        if history is None or history.empty:
            raise RuntimeError("No price history returned")
        return history.copy()

    @property
    def failures(self) -> dict[str, str]:
        return dict(self._failures_by_ticker)


class PreferredIntradaySnapshotMarketDataProvider:
    def __init__(self, base_provider: YFinanceMarketDataProvider, settings: Settings) -> None:
        self.base_provider = base_provider
        self.settings = settings
        self.snapshot = None

    def prepare(self, tickers: list[TickerInput], context: PipelineContext) -> None:
        prepare = getattr(self.base_provider, "prepare", None)
        if callable(prepare):
            prepare(tickers, context)
        self.snapshot = discover_latest_intraday_snapshot(self.settings.intraday_output_root, context.run_date)

    def fetch_history(self, ticker: TickerInput, context: PipelineContext) -> pd.DataFrame:
        history = self.base_provider.fetch_history(ticker, context)
        if self.snapshot is None:
            return history

        staged_quote = self.snapshot.quotes_by_ticker.get(ticker.ticker)
        if staged_quote is None:
            return history

        from screener.data.market_data import normalize_ohlcv_rows

        rows = history.sort_values("date").to_dict("records")
        bars = normalize_ohlcv_rows(ticker.ticker, rows)
        merged_bars = merge_history_with_staged_quote(bars, staged_quote)
        return pd.DataFrame(
            [
                {
                    "date": bar.trading_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "adj_close": bar.adj_close,
                    "volume": bar.volume,
                }
                for bar in merged_bars
            ]
        )

    @property
    def failures(self) -> dict[str, str]:
        return dict(getattr(self.base_provider, "failures", {}))


class TechnicalIndicatorEngine:
    def compute(self, history: pd.DataFrame, ticker: TickerInput, context: PipelineContext) -> dict[str, Any]:
        if history.empty:
            raise ValueError("Price history is empty")

        rows = history.sort_values("date").to_dict("records")
        bars = []
        for row in rows:
            bars.append(
                {
                    "Date": row["date"],
                    "Open": row["open"],
                    "High": row["high"],
                    "Low": row["low"],
                    "Close": row["close"],
                    "Adj Close": row.get("adj_close", row["close"]),
                    "Volume": row["volume"],
                }
            )

        from screener.data.market_data import normalize_ohlcv_rows

        enriched_rows = add_indicator_columns(normalize_ohlcv_rows(ticker.ticker, bars))
        latest = dict(enriched_rows[-1])
        closes = [float(row["close"]) for row in enriched_rows]
        volumes = [float(row["volume"]) for row in enriched_rows]
        rsi_values = [row["rsi_14"] for row in enriched_rows]

        latest["bars_available"] = len(enriched_rows)
        latest["average_volume_20d"] = rolling_mean(volumes, 20)[-1]
        latest["close_improvement_streak"] = _close_improvement_streak(closes)
        latest["rsi_3d_change"] = _latest_change(rsi_values, 3)
        latest["market_context_score"] = 10.0
        return latest


class RankedCandidateScorer:
    def evaluate(
        self,
        ticker: TickerInput,
        indicators: dict[str, Any],
        context: PipelineContext,
    ) -> CandidateResult | None:
        ranked = rank_candidates([{**indicators, "ticker": ticker.ticker}])
        if not ranked:
            return None

        candidate = ranked[0]
        return CandidateResult(
            ticker=candidate.ticker,
            score=float(candidate.score),
            subscores=ScoreBreakdown(**{key: float(value) for key, value in candidate.subscores.items()}),
            close=_maybe_float(candidate.snapshot.get("close")),
            lower_bb=_maybe_float(candidate.snapshot.get("bb_lower")),
            rsi14=_maybe_float(candidate.snapshot.get("rsi_14")),
            distance_to_20d_low=_maybe_float(candidate.snapshot.get("distance_to_20d_low")),
            reasons=candidate.reasons,
            risks=candidate.risks,
            generated_at=context.generated_at,
        )


class ScreenPipeline:
    def __init__(
        self,
        settings: Settings,
        universe_provider: UniverseProvider | None = None,
        market_data_provider: MarketDataProvider | None = None,
        indicator_engine: IndicatorEngine | None = None,
        candidate_scorer: CandidateScorer | None = None,
    ) -> None:
        self.settings = settings
        self.universe_provider = universe_provider or StaticUniverseProvider()
        self.market_data_provider = market_data_provider or build_market_data_provider(settings)
        self.indicator_engine = indicator_engine or TechnicalIndicatorEngine()
        self.candidate_scorer = candidate_scorer or RankedCandidateScorer()

    def run(self, context: PipelineContext) -> tuple[ScreenRunResult, RunArtifacts]:
        generated_at = context.generated_at
        tickers = self.universe_provider.load_universe(context)
        candidates: list[CandidateResult] = []
        failures: list[str] = []

        prepare = getattr(self.market_data_provider, "prepare", None)
        if callable(prepare):
            prepare(tickers, context)

        provider_failures = getattr(self.market_data_provider, "failures", {})
        if isinstance(provider_failures, dict):
            failures.extend(f"{ticker}: {message}" for ticker, message in provider_failures.items())

        for ticker in tickers:
            if isinstance(provider_failures, dict) and ticker.ticker in provider_failures:
                continue
            try:
                history = self.market_data_provider.fetch_history(ticker, context)
                indicators = self.indicator_engine.compute(history, ticker, context)
                candidate = self.candidate_scorer.evaluate(ticker, indicators, context)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:  # pragma: no cover, defensive integration guard
                failures.append(f"{ticker.ticker}: {exc}")

        candidates.sort(key=lambda candidate: (-candidate.score, candidate.ticker))

        result = ScreenRunResult(
            metadata=RunMetadata(
                run_date=context.run_date,
                generated_at=generated_at,
                universe=context.universe_name,
                run_mode=context.run_mode,
                dry_run=context.dry_run,
                artifact_directory=context.output_dir,
                data_failures=failures,
                notes=list(self.settings.default_notes),
            ),
            candidates=candidates,
        )

        artifacts = RunArtifacts()
        if not context.dry_run:
            artifacts = self._write_artifacts(result, context.output_dir)
        return result, artifacts

    def _write_artifacts(self, result: ScreenRunResult, output_dir: Path) -> RunArtifacts:
        ensure_directory(output_dir)
        markdown_path = write_text(
            output_dir / self.settings.markdown_report_name,
            build_markdown_report(result),
        )
        json_report_path = write_json(
            output_dir / self.settings.json_report_name,
            build_json_report(result),
        )
        metadata_path = write_json(
            output_dir / self.settings.metadata_report_name,
            result.metadata.model_dump(mode="json"),
        )
        return RunArtifacts(
            markdown_path=markdown_path,
            json_report_path=json_report_path,
            metadata_path=metadata_path,
        )


def build_market_data_provider(settings: Settings) -> YFinanceMarketDataProvider:
    fetcher = build_market_data_fetcher(
        settings.market_data_provider,
        twelve_data_api_key=settings.twelve_data_api_key,
        twelve_data_base_url=settings.twelve_data_base_url,
    )
    provider = YFinanceMarketDataProvider(fetcher=fetcher)
    if settings.daily_intraday_source_mode == "prefer-staged":
        return PreferredIntradaySnapshotMarketDataProvider(provider, settings)
    return provider


def _close_improvement_streak(closes: list[float]) -> int:
    if len(closes) < 2:
        return 0
    streak = 0
    for index in range(len(closes) - 1, 0, -1):
        if closes[index] > closes[index - 1]:
            streak += 1
        else:
            break
    return streak


def _latest_change(values: list[float | None], periods: int) -> float:
    valid = [float(value) for value in values if value is not None]
    if len(valid) <= periods:
        return 0.0
    return valid[-1] - valid[-1 - periods]


def _maybe_float(value: Any) -> float | None:
    return None if value is None else float(value)


def build_context(run_date, generated_at: datetime | None = None, dry_run: bool = False, output_dir: Path | str = Path("output"), run_mode: str = "daily", universe_name: str = "NASDAQ-100") -> PipelineContext:
    return PipelineContext(
        run_date=run_date,
        generated_at=generated_at or datetime.now().astimezone(),
        dry_run=dry_run,
        output_dir=Path(output_dir),
        run_mode=run_mode,
        universe_name=universe_name,
    )
