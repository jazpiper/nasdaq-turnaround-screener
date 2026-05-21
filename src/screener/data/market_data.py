from __future__ import annotations

import ipaddress
import json
from json import JSONDecodeError
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen

from screener.data.resilience import (
    DEFAULT_RESILIENCE_STATE,
    MarketDataRateLimitError,
    ProviderResilienceState,
    build_source_status,
    classify_provider_error,
    derive_market_data_reliability_label,
    normalize_ticker_list,
    retry_with_backoff,
    sanitize_provider_message,
)

DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0


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
    source_statuses: list[dict[str, object]] = field(default_factory=list)


class HttpResponseReader(Protocol):
    def __call__(self, url: str) -> str:
        """Read and return the response body for a URL."""


class MarketDataProviderError(RuntimeError):
    """Raised when a configured market data provider cannot be used."""


class MarketDataFetcher(Protocol):
    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        """Fetch normalized daily OHLCV bars for each ticker."""


def _validate_twelve_data_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise MarketDataProviderError("Twelve Data base URL must use http or https")
    if not parsed.hostname:
        raise MarketDataProviderError("Twelve Data base URL must include a host")
    if parsed.username or parsed.password:
        raise MarketDataProviderError("Twelve Data base URL must not include userinfo")

    hostname = parsed.hostname.strip().lower().rstrip(".")
    if hostname in {"localhost"} or hostname.endswith(".localhost"):
        raise MarketDataProviderError("Twelve Data base URL host must not be localhost")

    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        return base_url

    if (
        host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_private
        or host_ip.is_unspecified
        or host_ip.is_reserved
    ):
        raise MarketDataProviderError("Twelve Data base URL host must be publicly routable")
    return base_url


def _read_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; nasdaq-turnaround-screener/0.1)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urlopen(request, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as response:  # pragma: no cover, exercised via injected reader in tests
            return response.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover, covered via direct fake in tests when practical
        if exc.code == 429:
            raise MarketDataRateLimitError(
                "HTTP 429 rate limited",
                retry_after_seconds=_parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None),
            ) from exc
        raise MarketDataProviderError(f"HTTP provider_error status={exc.code}") from exc


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


_CANONICAL_FIELD_ALIASES: Mapping[str, tuple[str, ...]] = {
    "Date": ("Date", "date", "datetime"),
    "Open": ("Open", "open"),
    "High": ("High", "high"),
    "Low": ("Low", "low"),
    "Close": ("Close", "close"),
    "Adj Close": ("Adj Close", "adj_close", "adjClose", "adjusted_close", "adjustedClose", "previous_close"),
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


def _flatten_yfinance_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        normalized_row: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(key, tuple):
                parts = [str(part) for part in key if part not in (None, "")]
                normalized_key = parts[-1] if len(parts) > 1 else parts[0]
            else:
                normalized_key = str(key)
            normalized_row[normalized_key] = value
        flattened.append(normalized_row)
    return flattened


def _load_json_response(response_reader: HttpResponseReader, url: str) -> dict[str, Any]:
    try:
        payload = json.loads(response_reader(url))
    except JSONDecodeError as exc:
        raise MarketDataProviderError("provider response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise MarketDataProviderError("Provider response must be a JSON object")
    return payload


def _finnhub_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("s") not in {None, "ok"}:
        message = sanitize_provider_message(payload.get("error") or payload.get("message") or "Finnhub request failed")
        raise MarketDataProviderError(message)

    timestamps = payload.get("t")
    opens = payload.get("o")
    highs = payload.get("h")
    lows = payload.get("l")
    closes = payload.get("c")
    volumes = payload.get("v")
    if not all(isinstance(series, list) for series in (timestamps, opens, highs, lows, closes, volumes)):
        raise MarketDataProviderError("Finnhub response did not include OHLCV series")

    timestamps_list = cast(list[Any], timestamps)
    opens_list = cast(list[Any], opens)
    highs_list = cast(list[Any], highs)
    lows_list = cast(list[Any], lows)
    closes_list = cast(list[Any], closes)
    volumes_list = cast(list[Any], volumes)

    lengths = {len(timestamps_list), len(opens_list), len(highs_list), len(lows_list), len(closes_list), len(volumes_list)}
    if len(lengths) != 1:
        raise MarketDataProviderError("Finnhub response series lengths did not match")

    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps_list):
        rows.append(
            {
                "datetime": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat(),
                "open": opens_list[index],
                "high": highs_list[index],
                "low": lows_list[index],
                "close": closes_list[index],
                "adj_close": closes_list[index],
                "volume": volumes_list[index],
            }
        )
    return rows


def _fmp_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "historical" in payload:
        historical = payload.get("historical")
        if not isinstance(historical, list):
            raise MarketDataProviderError("FMP response did not include historical rows")
        return [dict(row) for row in historical if isinstance(row, dict)]
    message = payload.get("Error Message") or payload.get("message") or payload.get("error") or "FMP request failed"
    raise MarketDataProviderError(sanitize_provider_message(message))


class FinnhubDailyBarFetcher:
    """Fetch daily OHLCV bars from Finnhub stock candle endpoint."""

    provider_name = "finnhub"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://finnhub.io/api/v1/stock/candle",
        response_reader: HttpResponseReader | None = None,
        lookback_days: int = 120,
    ) -> None:
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY") or os.getenv("SCREENER_FINNHUB_API_KEY")
        self.base_url = base_url
        self.response_reader = response_reader or _read_url
        self.lookback_days = lookback_days

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        if not self.api_key:
            raise MarketDataProviderError("Finnhub API key is required")

        ticker_list = normalize_ticker_list(tickers)
        bars_by_ticker: dict[str, list[DailyBar]] = {}
        failed_tickers: dict[str, str] = {}
        end_ts = int(datetime.now(tz=timezone.utc).timestamp())
        start_ts = end_ts - max(self.lookback_days, 1) * 86400

        for ticker in ticker_list:
            params = urlencode({"symbol": ticker, "resolution": "D", "from": str(start_ts), "to": str(end_ts), "token": self.api_key})
            try:
                payload = _load_json_response(self.response_reader, f"{self.base_url}?{params}")
                rows = _finnhub_rows_from_payload(payload)
                bars = normalize_ohlcv_rows(ticker, rows)
                if not bars:
                    raise ValueError("No price rows returned")
                bars_by_ticker[ticker] = bars
            except Exception as exc:
                failed_tickers[ticker] = sanitize_provider_message(exc)

        status = build_source_status(
            provider=self.provider_name,
            role="primary",
            attempted=len(ticker_list),
            successful=len(bars_by_ticker),
            failed=len(failed_tickers),
            message=next(iter(failed_tickers.values()), None),
        ).as_dict()
        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=failed_tickers, source_statuses=[status])


class FMPDailyBarFetcher:
    """Fetch daily OHLCV bars from Financial Modeling Prep historical-price-full endpoint."""

    provider_name = "fmp"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://financialmodelingprep.com/api/v3/historical-price-full",
        response_reader: HttpResponseReader | None = None,
        outputsize: int = 120,
    ) -> None:
        self.api_key = api_key or os.getenv("FMP_API_KEY") or os.getenv("FINANCIAL_MODELING_PREP_API_KEY") or os.getenv("SCREENER_FMP_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.response_reader = response_reader or _read_url
        self.outputsize = outputsize

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        if not self.api_key:
            raise MarketDataProviderError("FMP API key is required")

        ticker_list = normalize_ticker_list(tickers)
        bars_by_ticker: dict[str, list[DailyBar]] = {}
        failed_tickers: dict[str, str] = {}

        for ticker in ticker_list:
            params = urlencode({"timeseries": str(self.outputsize), "apikey": self.api_key})
            try:
                payload = _load_json_response(self.response_reader, f"{self.base_url}/{ticker}?{params}")
                rows = _fmp_rows_from_payload(payload)
                bars = normalize_ohlcv_rows(ticker, rows)
                if not bars:
                    raise ValueError("No price rows returned")
                bars_by_ticker[ticker] = bars
            except Exception as exc:
                failed_tickers[ticker] = sanitize_provider_message(exc)

        status = build_source_status(
            provider=self.provider_name,
            role="primary",
            attempted=len(ticker_list),
            successful=len(bars_by_ticker),
            failed=len(failed_tickers),
            message=next(iter(failed_tickers.values()), None),
        ).as_dict()
        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=failed_tickers, source_statuses=[status])


class YFinanceDailyBarFetcher:
    """Fetch daily OHLCV bars via yfinance while keeping the rest of the code provider-agnostic."""

    provider_name = "yfinance"

    def __init__(
        self,
        *,
        period: str = "6mo",
        interval: str = "1d",
        auto_adjust: bool = False,
        batch_size: int | None = None,
        batch_pause_seconds: float = 0.0,
        threads: bool = True,
        daily_request_cap: int | None = None,
        quota_state_path: str | Path | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.period = period
        self.interval = interval
        self.auto_adjust = auto_adjust
        self.batch_size = batch_size
        self.batch_pause_seconds = max(batch_pause_seconds, 0.0)
        self.threads = threads
        self.daily_request_cap = daily_request_cap
        self.quota_state_path = Path(quota_state_path) if quota_state_path else None
        self.sleeper = sleeper or time.sleep

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        ticker_list = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
        if not ticker_list:
            status = build_source_status(
                provider=self.provider_name,
                role="primary",
                attempted=0,
                successful=0,
                failed=0,
            ).as_dict()
            return FetchResult(bars_by_ticker={}, failed_tickers={}, source_statuses=[status])

        try:
            import yfinance as yf
        except ModuleNotFoundError as exc:
            raise RuntimeError("yfinance is required to fetch market data") from exc

        bars_by_ticker: dict[str, list[DailyBar]] = {}
        failed_tickers: dict[str, str] = {}

        for batch_index, batch in enumerate(_chunked(ticker_list, self.batch_size)):
            if batch_index and self.batch_pause_seconds > 0:
                self.sleeper(self.batch_pause_seconds)
            if not self._reserve_daily_request_quota(len(batch)):
                for ticker in batch:
                    failed_tickers[ticker] = "Skipped: yfinance daily request cap would be exceeded"
                continue
            try:
                data = yf.download(
                    tickers=batch,
                    period=self.period,
                    interval=self.interval,
                    group_by="ticker",
                    auto_adjust=self.auto_adjust,
                    progress=False,
                    threads=self.threads,
                )
            except Exception as exc:
                message = sanitize_provider_message(exc)
                for ticker in batch:
                    failed_tickers[ticker] = message
                continue
            if data is None:
                for ticker in batch:
                    failed_tickers[ticker] = "No price rows returned"
                continue

            for ticker in batch:
                try:
                    ticker_frame = data[ticker] if len(batch) > 1 else data
                    rows = _flatten_yfinance_rows(ticker_frame.reset_index().to_dict("records"))
                    bars = normalize_ohlcv_rows(ticker, rows)
                    if not bars:
                        raise ValueError("No price rows returned")
                    bars_by_ticker[ticker] = bars
                except Exception as exc:
                    failed_tickers[ticker] = sanitize_provider_message(exc)

        status = build_source_status(
            provider=self.provider_name,
            role="primary",
            attempted=len(ticker_list),
            successful=len(bars_by_ticker),
            failed=len(failed_tickers),
            message=next(iter(failed_tickers.values()), None),
        ).as_dict()
        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=failed_tickers, source_statuses=[status])

    def _reserve_daily_request_quota(self, request_count: int) -> bool:
        if not self.daily_request_cap or self.daily_request_cap <= 0 or not self.quota_state_path:
            return True
        today = datetime.now(timezone.utc).date().isoformat()
        path = self.quota_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        state: dict[str, object] = {}
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, JSONDecodeError):
                state = {}
        raw_used = state.get("used", 0) if state.get("date") == today else 0
        try:
            used = int(cast(Any, raw_used))
        except (TypeError, ValueError):
            used = 0
        if used + request_count > self.daily_request_cap:
            return False
        state = {
            "date": today,
            "used": used + request_count,
            "cap": self.daily_request_cap,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return True


def _chunked(items: list[str], size: int | None) -> list[list[str]]:
    if size is None or size <= 0 or size >= len(items):
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


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
        max_retries: int = 2,
        initial_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 5.0,
        cooldown_seconds: float = 120.0,
        cache_ttl_seconds: float = 300.0,
        stale_cache_ttl_seconds: float = 1800.0,
        sleeper: Callable[[float], None] | None = None,
        resilience_state: ProviderResilienceState | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TWELVE_DATA_API_KEY")
        self.interval = interval
        self.outputsize = outputsize
        self.base_url = _validate_twelve_data_base_url(base_url)
        self.response_reader = response_reader or _read_url
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.cooldown_seconds = cooldown_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.stale_cache_ttl_seconds = stale_cache_ttl_seconds
        self.sleeper = sleeper or time.sleep
        self.resilience_state = resilience_state or DEFAULT_RESILIENCE_STATE

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        if not self.api_key:
            raise MarketDataProviderError("Twelve Data API key is required")

        ticker_list = normalize_ticker_list(tickers)
        bars_by_ticker: dict[str, list[DailyBar]] = {}
        failed_tickers: dict[str, str] = {}
        retry_count = 0
        used_cache = False
        used_stale_cache = False
        cooldown_active = False

        for ticker in ticker_list:
            cache_key = self._cache_key(ticker)
            cooldown_key = self._cooldown_key()
            cached_bars, stale = self.resilience_state.get_cache(
                cache_key,
                ttl_seconds=self.cache_ttl_seconds,
                stale_ttl_seconds=self.stale_cache_ttl_seconds,
            )
            if cached_bars is not None and not stale:
                bars_by_ticker[ticker] = list(cached_bars)
                used_cache = True
                continue
            if self.resilience_state.is_cooling_down(cooldown_key):
                cooldown_active = True
                if cached_bars is not None:
                    bars_by_ticker[ticker] = list(cached_bars)
                    used_cache = True
                    used_stale_cache = True
                else:
                    failed_tickers[ticker] = "rate_limited: provider cooldown active"
                continue
            try:
                bars, attempts = retry_with_backoff(
                    lambda ticker=ticker: self._fetch_ticker_once(ticker),
                    max_retries=self.max_retries,
                    initial_backoff_seconds=self.initial_backoff_seconds,
                    max_backoff_seconds=self.max_backoff_seconds,
                    sleeper=self.sleeper,
                )
                retry_count += attempts
                if not bars:
                    raise ValueError("No price rows returned")
                bars_by_ticker[ticker] = bars
                self.resilience_state.set_cache(cache_key, list(bars))
            except Exception as exc:
                message = sanitize_provider_message(exc)
                failed_tickers[ticker] = message
                if classify_provider_error(message) == "rate_limited":
                    self.resilience_state.start_cooldown(cooldown_key, self.cooldown_seconds)
                    if cached_bars is not None:
                        bars_by_ticker[ticker] = list(cached_bars)
                        failed_tickers.pop(ticker, None)
                        used_cache = True
                        used_stale_cache = True

        status = build_source_status(
            provider=self.provider_name,
            role="primary",
            attempted=len(ticker_list),
            successful=len(bars_by_ticker),
            failed=len(failed_tickers),
            retry_count=retry_count,
            used_cache=used_cache,
            used_stale_cache=used_stale_cache,
            cooldown_active=cooldown_active,
            message=next(iter(failed_tickers.values()), None),
        ).as_dict()
        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=failed_tickers, source_statuses=[status])

    def _fetch_ticker_once(self, ticker: str) -> list[DailyBar]:
        params = urlencode(
            {
                "symbol": ticker,
                "interval": self.interval,
                "outputsize": str(self.outputsize),
                "format": "JSON",
                "apikey": self.api_key,
            }
        )
        try:
            payload = json.loads(self.response_reader(f"{self.base_url}?{params}"))
        except JSONDecodeError as exc:
            raise MarketDataProviderError("provider response was not valid JSON") from exc
        if "status" in payload and payload["status"] == "error":
            message = sanitize_provider_message(payload.get("message", "Twelve Data request failed"))
            if classify_provider_error(message) == "rate_limited":
                raise MarketDataRateLimitError(message)
            raise MarketDataProviderError(message)

        values = payload.get("values")
        if not isinstance(values, list):
            message = sanitize_provider_message(payload.get("message", "Twelve Data response did not include OHLCV values"))
            if classify_provider_error(message) == "rate_limited":
                raise MarketDataRateLimitError(message)
            raise MarketDataProviderError(message)

        return normalize_ohlcv_rows(ticker, values)

    def _fetch_ticker(self, ticker: str) -> list[DailyBar]:
        return self._fetch_ticker_once(ticker)

    def _cache_key(self, ticker: str) -> tuple[object, ...]:
        return (self.provider_name, self.base_url, self.interval, self.outputsize, ticker)

    def _cooldown_key(self) -> tuple[object, ...]:
        return (self.provider_name, self.base_url, self.interval)


class ResilientMarketDataFetcher:
    """Try providers in order and keep per-source status instead of hiding partial failures."""

    provider_name = "resilient"

    def __init__(self, providers: list[tuple[str, MarketDataFetcher]]) -> None:
        if not providers:
            raise MarketDataProviderError("At least one market data provider is required")
        self.providers = providers

    def fetch(self, tickers: Iterable[str]) -> FetchResult:
        remaining = normalize_ticker_list(tickers)
        bars_by_ticker: dict[str, list[DailyBar]] = {}
        final_failures: dict[str, str] = {}
        source_statuses: list[dict[str, object]] = []

        for index, (provider_name, fetcher) in enumerate(self.providers):
            if not remaining:
                break
            role = "primary" if index == 0 else "fallback"
            attempted = list(remaining)
            try:
                result = fetcher.fetch(attempted)
            except Exception as exc:
                message = sanitize_provider_message(exc)
                result = FetchResult(
                    bars_by_ticker={},
                    failed_tickers={ticker: message for ticker in attempted},
                    source_statuses=[
                        build_source_status(
                            provider=provider_name,
                            role=role,
                            attempted=len(attempted),
                            successful=0,
                            failed=len(attempted),
                            message=message,
                        ).as_dict()
                    ],
                )

            bars_by_ticker.update(result.bars_by_ticker)
            final_failures = {
                ticker: sanitize_provider_message(message)
                for ticker, message in result.failed_tickers.items()
                if ticker not in bars_by_ticker
            }
            source_statuses.extend(
                _with_status_role(status, provider_name=provider_name, role=role)
                for status in result.source_statuses
            )
            remaining = [ticker for ticker in attempted if ticker not in bars_by_ticker]

        if len(self.providers) > 1 and source_statuses:
            fallback_names = [name for name, _ in self.providers[1:]]
            source_statuses = [
                {**status, "fallback_provider": fallback_names[0]}
                if status.get("role") == "primary" and fallback_names
                else status
                for status in source_statuses
            ]
        return FetchResult(bars_by_ticker=bars_by_ticker, failed_tickers=final_failures, source_statuses=source_statuses)


def _with_status_role(status: dict[str, object], *, provider_name: str, role: str) -> dict[str, object]:
    payload = dict(status)
    payload["provider"] = str(payload.get("provider") or provider_name)
    payload["role"] = role
    if payload.get("message"):
        payload["message"] = sanitize_provider_message(payload["message"])
    return payload


def build_market_data_fetcher(
    provider: str = "yfinance",
    *,
    twelve_data_api_key: str | None = None,
    twelve_data_base_url: str = "https://api.twelvedata.com/time_series",
    finnhub_api_key: str | None = None,
    fmp_api_key: str | None = None,
) -> MarketDataFetcher:
    provider_names = [name.strip().lower() for name in provider.split(",") if name.strip()]
    if not provider_names:
        raise MarketDataProviderError("Market data provider cannot be blank")

    built_providers: list[tuple[str, MarketDataFetcher]] = []
    for provider_name in provider_names:
        fetcher = _build_single_market_data_fetcher(
            provider_name,
            twelve_data_api_key=twelve_data_api_key,
            twelve_data_base_url=twelve_data_base_url,
            finnhub_api_key=finnhub_api_key,
            fmp_api_key=fmp_api_key,
            allow_missing_credentials=len(provider_names) > 1,
        )
        if fetcher is None:
            continue
        built_providers.append((_canonical_provider_name(provider_name), fetcher))

    if not built_providers:
        raise MarketDataProviderError("No usable market data providers are configured")
    if len(built_providers) == 1:
        return built_providers[0][1]
    return ResilientMarketDataFetcher(built_providers)


def _canonical_provider_name(provider: str) -> str:
    normalized_provider = provider.strip().lower()
    if normalized_provider in {"yfinance", "yf"}:
        return "yfinance"
    if normalized_provider in {"twelve-data", "twelvedata", "twelve_data"}:
        return "twelve-data"
    if normalized_provider in {"finnhub"}:
        return "finnhub"
    if normalized_provider in {"fmp", "financial-modeling-prep", "financial_modeling_prep"}:
        return "fmp"
    raise MarketDataProviderError(f"Unsupported market data provider: {provider}")


def _optional_positive_int_env(name: str) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        parsed = int(raw_value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _nonnegative_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        return default
    return max(parsed, 0.0)


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _build_single_market_data_fetcher(
    provider: str,
    *,
    twelve_data_api_key: str | None,
    twelve_data_base_url: str,
    finnhub_api_key: str | None,
    fmp_api_key: str | None,
    allow_missing_credentials: bool,
) -> MarketDataFetcher | None:
    canonical_provider = _canonical_provider_name(provider)
    if canonical_provider == "yfinance":
        return YFinanceDailyBarFetcher(
            batch_size=_optional_positive_int_env("SCREENER_YFINANCE_BATCH_SIZE"),
            batch_pause_seconds=_nonnegative_float_env("SCREENER_YFINANCE_BATCH_PAUSE_SECONDS", 0.0),
            threads=_bool_env("SCREENER_YFINANCE_THREADS", True),
            daily_request_cap=_optional_positive_int_env("SCREENER_YFINANCE_DAILY_REQUEST_CAP"),
            quota_state_path=os.getenv("SCREENER_YFINANCE_QUOTA_STATE_PATH"),
        )
    if canonical_provider == "twelve-data":
        if allow_missing_credentials and not (twelve_data_api_key or os.getenv("TWELVE_DATA_API_KEY")):
            return None
        return TwelveDataDailyBarFetcher(
            api_key=twelve_data_api_key,
            base_url=twelve_data_base_url,
        )
    if canonical_provider == "finnhub":
        if allow_missing_credentials and not (finnhub_api_key or os.getenv("FINNHUB_API_KEY") or os.getenv("SCREENER_FINNHUB_API_KEY")):
            return None
        return FinnhubDailyBarFetcher(api_key=finnhub_api_key)
    if canonical_provider == "fmp":
        if allow_missing_credentials and not (fmp_api_key or os.getenv("FMP_API_KEY") or os.getenv("FINANCIAL_MODELING_PREP_API_KEY") or os.getenv("SCREENER_FMP_API_KEY")):
            return None
        return FMPDailyBarFetcher(api_key=fmp_api_key)
    raise MarketDataProviderError(f"Unsupported market data provider: {provider}")
