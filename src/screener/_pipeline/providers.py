from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from screener.config import Settings
from screener.data import (
    EarningsCalendarProvider,
    FileBackedEarningsCalendarProvider,
    MarketDataFetcher,
    YFinanceDailyBarFetcher,
    build_market_data_fetcher,
)
from screener.indicators.technicals import add_indicator_columns, latest_weekly_context, rolling_mean
from screener.intraday_artifacts import discover_latest_intraday_snapshot, merge_history_with_staged_quote
from screener.models import PipelineContext, TickerInput
from screener.universe import load_static_universe
from screener.universe.nasdaq100_names import NASDAQ_100_COMPANY_NAMES

from .context import _close_improvement_streak, _latest_change, _percent_return


class StaticUniverseProvider:
    def __init__(self, tickers: Iterable[str] | None = None) -> None:
        self._tickers = tuple(tickers) if tickers is not None else None

    def load_universe(self, context: PipelineContext) -> list[TickerInput]:
        definition = load_static_universe(tickers=self._tickers, name=context.universe_name)
        return [
            TickerInput(ticker=ticker, name=NASDAQ_100_COMPANY_NAMES.get(ticker))
            for ticker in definition.tickers
        ]


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


def build_market_data_provider(settings: Settings) -> YFinanceMarketDataProvider | PreferredIntradaySnapshotMarketDataProvider:
    fetcher = build_market_data_fetcher(
        settings.market_data_provider,
        twelve_data_api_key=settings.twelve_data_api_key,
        twelve_data_base_url=settings.twelve_data_base_url,
    )
    provider = YFinanceMarketDataProvider(fetcher=fetcher)
    if settings.daily_intraday_source_mode == "prefer-staged":
        return PreferredIntradaySnapshotMarketDataProvider(provider, settings)
    return provider


__all__ = [
    "PreferredIntradaySnapshotMarketDataProvider",
    "StaticUniverseProvider",
    "TechnicalIndicatorEngine",
    "YFinanceMarketDataProvider",
    "build_earnings_calendar_provider",
    "build_market_data_provider",
]

