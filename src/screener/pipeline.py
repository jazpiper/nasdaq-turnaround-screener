from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from screener.config import Settings
from screener.data import (
    EarningsCalendarProvider,
    EarningsInfo,
    FileBackedEarningsCalendarProvider,
    MarketDataFetcher,
    YFinanceDailyBarFetcher,
    build_market_data_fetcher,
)
from screener.indicators.technicals import add_indicator_columns, latest_weekly_context, rolling_mean
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

INDICATOR_SNAPSHOT_SCHEMA_VERSION = 2
BENCHMARK_TICKER = "QQQ"
INDICATOR_SNAPSHOT_KEYS: tuple[str, ...] = (
    "close",
    "low",
    "bb_lower",
    "rsi_14",
    "sma_5",
    "sma_20",
    "sma_60",
    "atr_14",
    "atr_14_pct",
    "daily_range_pct",
    "bb_width_pct",
    "close_above_open",
    "close_location_value",
    "lower_wick_ratio",
    "upper_wick_ratio",
    "real_body_pct",
    "gap_down_pct",
    "gap_down_reclaim",
    "inside_day",
    "bullish_engulfing_like",
    "distance_to_20d_low",
    "distance_to_60d_low",
    "average_volume_20d",
    "volume_ratio_20d",
    "close_improvement_streak",
    "rsi_3d_change",
    "market_context_score",
    "qqq_return_20d",
    "qqq_return_60d",
    "stock_return_20d",
    "stock_return_60d",
    "rel_strength_20d_vs_qqq",
    "rel_strength_60d_vs_qqq",
    "relative_strength_score",
    "earnings_data_available",
    "next_earnings_date",
    "days_to_next_earnings",
    "days_since_last_earnings",
    "earnings_penalty",
    "volatility_penalty",
    "weekly_bars_available",
    "weekly_close",
    "weekly_sma_5",
    "weekly_sma_10",
    "weekly_close_improving",
    "weekly_trend_penalty",
    "weekly_trend_severe_damage",
)


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

        normalized_bars = normalize_ohlcv_rows(ticker.ticker, bars)
        enriched_rows = add_indicator_columns(normalized_bars)
        latest = dict(enriched_rows[-1])
        closes = [float(row["close"]) for row in enriched_rows]
        volumes = [float(row["volume"]) for row in enriched_rows]
        rsi_values = [row["rsi_14"] for row in enriched_rows]
        weekly_context = latest_weekly_context(normalized_bars)

        latest["bars_available"] = len(enriched_rows)
        latest["average_volume_20d"] = rolling_mean(volumes, 20)[-1]
        latest["close_improvement_streak"] = _close_improvement_streak(closes)
        latest["rsi_3d_change"] = _latest_change(rsi_values, 3)
        latest["stock_return_20d"] = _percent_return(closes, 20)
        latest["stock_return_60d"] = _percent_return(closes, 60)
        latest.update(weekly_context)
        latest["market_context_score"] = 10.0 - float(weekly_context["weekly_trend_penalty"])
        return latest


def build_earnings_calendar_provider(settings: Settings) -> EarningsCalendarProvider | None:
    if settings.earnings_calendar_path is None:
        return None
    return FileBackedEarningsCalendarProvider(settings.earnings_calendar_path)


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
            indicator_snapshot=build_indicator_snapshot(candidate.snapshot),
            snapshot_schema_version=INDICATOR_SNAPSHOT_SCHEMA_VERSION,
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

    def run(self, context: PipelineContext) -> tuple[ScreenRunResult, RunArtifacts]:
        generated_at = context.generated_at
        tickers = self.universe_provider.load_universe(context)
        candidates: list[CandidateResult] = []
        failures: list[str] = []
        notes = list(self.settings.default_notes)

        prepare = getattr(self.market_data_provider, "prepare", None)
        if callable(prepare):
            prepare(tickers, context)

        earnings_by_ticker: dict[str, EarningsInfo] = {}
        if self.earnings_calendar_provider is not None:
            try:
                earnings_by_ticker = self.earnings_calendar_provider.fetch([item.ticker for item in tickers], context.run_date)
            except Exception as exc:  # pragma: no cover, defensive integration guard
                notes.append(f"Earnings calendar unavailable: {exc}")

        benchmark_context: dict[str, Any] = {}
        if self.benchmark_market_data_provider is not None:
            try:
                benchmark_context = fetch_benchmark_context(self.benchmark_market_data_provider, context)
            except Exception as exc:  # pragma: no cover, defensive integration guard
                notes.append(f"Benchmark context unavailable: {exc}")

        provider_failures = getattr(self.market_data_provider, "failures", {})
        if isinstance(provider_failures, dict):
            failures.extend(f"{ticker}: {message}" for ticker, message in provider_failures.items())

        for ticker in tickers:
            if isinstance(provider_failures, dict) and ticker.ticker in provider_failures:
                continue
            try:
                history = self.market_data_provider.fetch_history(ticker, context)
                indicators = self.indicator_engine.compute(history, ticker, context)
                indicators = merge_benchmark_context(indicators, benchmark_context)
                indicators = merge_earnings_context(indicators, earnings_by_ticker.get(ticker.ticker))
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
                notes=notes,
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


def _percent_return(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    previous_close = closes[-1 - periods]
    if previous_close == 0:
        return None
    return ((closes[-1] / previous_close) - 1.0) * 100.0


def fetch_benchmark_context(market_data_provider: MarketDataProvider, context: PipelineContext) -> dict[str, Any]:
    benchmark = TickerInput(ticker=BENCHMARK_TICKER)
    prepare = getattr(market_data_provider, "prepare", None)
    if callable(prepare):
        prepare([benchmark], context)
    history = market_data_provider.fetch_history(benchmark, context)
    closes = [float(value) for value in history.sort_values("date")["close"].tolist()]
    benchmark_context = {
        "qqq_return_20d": _percent_return(closes, 20),
        "qqq_return_60d": _percent_return(closes, 60),
    }
    return benchmark_context


def merge_benchmark_context(indicators: dict[str, Any], benchmark_context: dict[str, Any]) -> dict[str, Any]:
    merged = dict(indicators)
    if not benchmark_context:
        return merged

    merged.update(benchmark_context)
    stock_return_20d = merged.get("stock_return_20d")
    qqq_return_20d = merged.get("qqq_return_20d")
    if stock_return_20d is not None and qqq_return_20d is not None:
        merged["rel_strength_20d_vs_qqq"] = float(stock_return_20d) - float(qqq_return_20d)

    stock_return_60d = merged.get("stock_return_60d")
    qqq_return_60d = merged.get("qqq_return_60d")
    if stock_return_60d is not None and qqq_return_60d is not None:
        merged["rel_strength_60d_vs_qqq"] = float(stock_return_60d) - float(qqq_return_60d)
    return merged


def merge_earnings_context(indicators: dict[str, Any], earnings_info: EarningsInfo | None) -> dict[str, Any]:
    merged = dict(indicators)
    merged["earnings_data_available"] = earnings_info is not None
    if earnings_info is None:
        return merged

    merged["next_earnings_date"] = (
        earnings_info.next_earnings_date.isoformat() if earnings_info.next_earnings_date is not None else None
    )
    merged["days_to_next_earnings"] = earnings_info.days_to_next_earnings
    merged["days_since_last_earnings"] = earnings_info.days_since_last_earnings
    return merged


def build_indicator_snapshot(indicators: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"schema_version": INDICATOR_SNAPSHOT_SCHEMA_VERSION}
    for key in INDICATOR_SNAPSHOT_KEYS:
        if key not in indicators:
            continue
        value = _snapshot_value(indicators[key])
        if value is not None:
            snapshot[key] = value
    return snapshot


def _maybe_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _snapshot_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item") and callable(value.item):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value
    return str(value)


def build_context(run_date, generated_at: datetime | None = None, dry_run: bool = False, output_dir: Path | str = Path("output"), run_mode: str = "daily", universe_name: str = "NASDAQ-100") -> PipelineContext:
    return PipelineContext(
        run_date=run_date,
        generated_at=generated_at or datetime.now().astimezone(),
        dry_run=dry_run,
        output_dir=Path(output_dir),
        run_mode=run_mode,
        universe_name=universe_name,
    )
