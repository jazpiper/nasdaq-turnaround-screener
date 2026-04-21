from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class DailyBar:
    ticker: str
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float


@dataclass(frozen=True)
class FetchResult:
    bars_by_ticker: dict[str, list[DailyBar]]
    failed_tickers: dict[str, str]


def _to_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().date()
    return datetime.fromisoformat(str(value)).date()


def _to_float(value: Any) -> float:
    if value is None:
        raise ValueError("Missing numeric value")
    number = float(value)
    if number != number:
        raise ValueError("NaN numeric value")
    return number


def normalize_ohlcv_rows(ticker: str, rows: Iterable[dict[str, Any]]) -> list[DailyBar]:
    normalized: list[DailyBar] = []
    for row in rows:
        normalized.append(
            DailyBar(
                ticker=ticker,
                trading_date=_to_date(row["Date"]),
                open=_to_float(row["Open"]),
                high=_to_float(row["High"]),
                low=_to_float(row["Low"]),
                close=_to_float(row["Close"]),
                adj_close=_to_float(row.get("Adj Close", row["Close"])),
                volume=_to_float(row["Volume"]),
            )
        )
    return sorted(normalized, key=lambda bar: bar.trading_date)


class YFinanceDailyBarFetcher:
    """Fetch daily OHLCV bars via yfinance while keeping the rest of the code provider-agnostic."""

    def __init__(self, *, period: str = "6mo", interval: str = "1d", auto_adjust: bool = False):
        self.period = period
        self.interval = interval
        self.auto_adjust = auto_adjust

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        ticker_list = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
        if not ticker_list:
            return FetchResult(bars_by_ticker={}, failed_tickers={})

        try:
            import yfinance as yf
        except ModuleNotFoundError as exc:
            raise RuntimeError("yfinance is required to fetch market data") from exc

        data = yf.download(
            tickers=ticker_list,
            period=self.period,
            interval=self.interval,
            group_by="ticker",
            auto_adjust=self.auto_adjust,
            progress=False,
            threads=True,
        )

        bars_by_ticker: dict[str, list[DailyBar]] = {}
        failed_tickers: dict[str, str] = {}

        for ticker in ticker_list:
            try:
                ticker_frame = data[ticker] if len(ticker_list) > 1 else data
                rows = ticker_frame.reset_index().to_dict("records")
                bars = normalize_ohlcv_rows(ticker, rows)
                if not bars:
                    raise ValueError("No price rows returned")
                bars_by_ticker[ticker] = bars
            except Exception as exc:
                failed_tickers[ticker] = str(exc)

        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=failed_tickers)
