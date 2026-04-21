from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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


class HttpResponseReader(Protocol):
    def __call__(self, url: str) -> str:
        """Read and return the response body for a URL."""


class MarketDataProviderError(RuntimeError):
    """Raised when a configured market data provider cannot be used."""


class MarketDataFetcher(Protocol):
    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        """Fetch normalized daily OHLCV bars for each ticker."""


def _read_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; nasdaq-turnaround-screener/0.1)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request) as response:  # pragma: no cover, exercised via injected reader in tests
        return response.read().decode("utf-8")


_CANONICAL_FIELD_ALIASES: Mapping[str, tuple[str, ...]] = {
    "Date": ("Date", "date", "datetime"),
    "Open": ("Open", "open"),
    "High": ("High", "high"),
    "Low": ("Low", "low"),
    "Close": ("Close", "close"),
    "Adj Close": ("Adj Close", "adj_close", "adjusted_close", "previous_close"),
    "Volume": ("Volume", "volume"),
}


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


def _pick_field(row: Mapping[str, Any], canonical_name: str) -> Any:
    for key in _CANONICAL_FIELD_ALIASES[canonical_name]:
        if key in row and row[key] not in (None, ""):
            return row[key]
    if canonical_name == "Adj Close":
        return _pick_field(row, "Close")
    raise KeyError(canonical_name)


def normalize_ohlcv_rows(ticker: str, rows: Iterable[Mapping[str, Any]]) -> list[DailyBar]:
    normalized: list[DailyBar] = []
    for row in rows:
        normalized.append(
            DailyBar(
                ticker=ticker,
                trading_date=_to_date(_pick_field(row, "Date")),
                open=_to_float(_pick_field(row, "Open")),
                high=_to_float(_pick_field(row, "High")),
                low=_to_float(_pick_field(row, "Low")),
                close=_to_float(_pick_field(row, "Close")),
                adj_close=_to_float(_pick_field(row, "Adj Close")),
                volume=_to_float(_pick_field(row, "Volume")),
            )
        )
    return sorted(normalized, key=lambda bar: bar.trading_date)


class YFinanceDailyBarFetcher:
    """Fetch daily OHLCV bars via yfinance while keeping the rest of the code provider-agnostic."""

    provider_name = "yfinance"

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


class TwelveDataDailyBarFetcher:
    """Fetch daily OHLCV bars from Twelve Data time_series endpoint."""

    provider_name = "twelve-data"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        interval: str = "1day",
        outputsize: int = 120,
        base_url: str = "https://api.twelvedata.com/time_series",
        response_reader: HttpResponseReader | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TWELVE_DATA_API_KEY")
        self.interval = interval
        self.outputsize = outputsize
        self.base_url = base_url
        self.response_reader = response_reader or _read_url

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        if not self.api_key:
            raise MarketDataProviderError("Twelve Data API key is required")

        bars_by_ticker: dict[str, list[DailyBar]] = {}
        failed_tickers: dict[str, str] = {}

        for ticker in [ticker.strip().upper() for ticker in tickers if ticker.strip()]:
            try:
                bars = self._fetch_ticker(ticker)
                if not bars:
                    raise ValueError("No price rows returned")
                bars_by_ticker[ticker] = bars
            except Exception as exc:
                failed_tickers[ticker] = str(exc)

        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=failed_tickers)

    def _fetch_ticker(self, ticker: str) -> list[DailyBar]:
        params = urlencode(
            {
                "symbol": ticker,
                "interval": self.interval,
                "outputsize": str(self.outputsize),
                "format": "JSON",
                "apikey": self.api_key,
            }
        )
        payload = json.loads(self.response_reader(f"{self.base_url}?{params}"))
        if "status" in payload and payload["status"] == "error":
            raise MarketDataProviderError(payload.get("message", "Twelve Data request failed"))

        values = payload.get("values")
        if not isinstance(values, list):
            raise MarketDataProviderError(payload.get("message", "Twelve Data response did not include OHLCV values"))

        return normalize_ohlcv_rows(ticker, values)


def build_market_data_fetcher(
    provider: str = "yfinance",
    *,
    twelve_data_api_key: str | None = None,
    twelve_data_base_url: str = "https://api.twelvedata.com/time_series",
) -> MarketDataFetcher:
    normalized_provider = provider.strip().lower()
    if normalized_provider in {"yfinance", "yf"}:
        return YFinanceDailyBarFetcher()
    if normalized_provider in {"twelve-data", "twelvedata", "twelve_data"}:
        return TwelveDataDailyBarFetcher(
            api_key=twelve_data_api_key,
            base_url=twelve_data_base_url,
        )
    raise MarketDataProviderError(f"Unsupported market data provider: {provider}")
